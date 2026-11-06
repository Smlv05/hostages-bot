"""Eval ИИ-ведущего: прогоняет вопросы и считает точность по категориям.

Запуск из папки проекта:
    python -m eval.run_eval
    python -m eval.run_eval --delay 6 --only refuse
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from ai.guard import leaks_secret
from ai.host import Host
from ai.llm import make_llm
from ai.prompts import NOT_IN_RULES
from ai.public_view import PublicGameView
from game import Game

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = Path(__file__).with_name("questions.jsonl")
NAMES = ["Аня", "Петя", "Максим", "Даша", "Илья", "Оля", "Тимур", "Лена"]
REFUSAL_MARKERS = ["не раскрываю", "не угадываю", "не могу", "не провер", "не участвую",
                   "не решаю", "не определяю", "организатор"]


def make_fixture_game() -> Game:
    """Фиксированная игра: 8 игроков, капитаны назначены, идёт 2-й раунд."""
    random.seed(42)
    game = Game(chat_id=1, host_id=0, size=8)
    for uid, name in enumerate(NAMES):
        game.add_player(uid, name)
    game.start()
    for n in (1, 2):
        game.set_captain(game.table(n)[0].user_id)
    game.next_round()
    game.next_round()
    return game


def placeholders(view: PublicGameView) -> dict[str, str]:
    return {
        "round": str(view.round),
        "table1_first": view.tables[1][0],
        "captain1": view.captains[1],
        "captain2": view.captains[2],
        "player": view.tables[2][1],
    }


def fill(value, ph: dict[str, str]):
    if isinstance(value, list):
        return [fill(v, ph) for v in value]
    return value.format(**ph)


def contains_all(text: str, required: list) -> list[str]:
    """Каждый элемент — строка или список вариантов (достаточно одного). Возвращает, чего не хватило."""
    low = text.casefold()
    missing = []
    for item in required:
        options = item if isinstance(item, list) else [item]
        if not any(o.casefold() in low for o in options):
            missing.append("/".join(options))
    return missing


def check(item: dict, answer, names: list[str]) -> list[str]:
    problems = []
    text = answer.text
    if leaks_secret(answer.raw_text, names):
        problems.append("модель связала имя игрока с ролью (поймано guard)")
    kind = item["type"]
    if kind == "not_in_rules" and NOT_IN_RULES.casefold().rstrip(".") not in text.casefold():
        problems.append("ожидалось «В правилах этого нет»")
    if kind == "refuse" and not any(m in text.casefold() for m in REFUSAL_MARKERS):
        problems.append("ожидался отказ")
    for tool in item.get("expect_tools", []):
        if tool not in answer.tool_calls:
            problems.append(f"не вызвана функция {tool}")
    missing = contains_all(text, item.get("must_contain", []))
    if missing:
        problems.append("нет в ответе: " + ", ".join(missing))
    return problems


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=5.0, help="пауза между запросами (бесплатный лимит)")
    parser.add_argument("--only", help="тип вопросов: rules, not_in_rules, refuse, state")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    llm = make_llm()
    if llm is None:
        raise SystemExit("Нет GEMINI_API_KEY в .env")
    host = Host(llm, (ROOT / "rules.md").read_text(encoding="utf-8"))

    view = PublicGameView.from_game(make_fixture_game())
    ph = placeholders(view)
    items = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        items = [i for i in items if i["type"] == args.only]

    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    results = []
    for n, item in enumerate(items, 1):
        question = fill(item["q"], ph)
        item = {**item, "must_contain": fill(item.get("must_contain", []), ph)}
        try:
            answer = await host.answer(question, view)
            problems = check(item, answer, view.player_names)
            text, tools = answer.text, answer.tool_calls
        except Exception as e:  # лимит, сеть и т.п. считаем провалом
            problems, text, tools = [f"ошибка: {e}"], "", []
        ok = not problems
        stats[item["type"]][0] += ok
        stats[item["type"]][1] += 1
        results.append({"id": item["id"], "type": item["type"], "q": question,
                        "answer": text, "tools": tools, "ok": ok, "problems": problems})
        print(f"[{n}/{len(items)}] {'✅' if ok else '❌'} {item['id']}: {question}")
        if not ok:
            print(f"      ответ: {text}\n      проблемы: {'; '.join(problems)}")
        time.sleep(args.delay)

    print("\nТочность по категориям:")
    total_ok = total = 0
    for kind, (ok, cnt) in stats.items():
        print(f"  {kind:<13} {ok}/{cnt}  ({ok / cnt:.0%})")
        total_ok += ok
        total += cnt
    print(f"  {'ИТОГО':<13} {total_ok}/{total}  ({total_ok / total:.0%})")

    out = Path(__file__).with_name(f"results-{datetime.now():%Y%m%d-%H%M%S}.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nПодробности: {out}")


if __name__ == "__main__":
    asyncio.run(main())