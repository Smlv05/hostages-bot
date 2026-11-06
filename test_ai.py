"""Тесты ИИ-части без настоящей LLM: проверяем, что секреты не могут утечь."""
import asyncio
import dataclasses

from ai.guard import leaks_secret
from ai.host import Host
from ai.llm import LLMResult
from ai.prompts import REFUSAL
from ai.public_view import PublicGameView
from ai.tips import TipProvider
from ai.tools import build_tools
from eval.run_eval import make_fixture_game
from game import ROLES


class FakeLLM:
    """Возвращает заданный текст и по очереди «вызывает» все переданные функции."""

    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.seen: list[str] = []

    async def run(self, system, user, tools=None):
        self.calls += 1
        outputs = [str(t.func()) for t in tools or []]
        self.seen.extend([system, user, *outputs])
        return LLMResult(self.text, [t.name for t in tools or []])


SECRET_WORDS = [r.key for r in ROLES.values()] + [r.name for r in ROLES.values()] + ["blue", "red"]


def test_public_view_has_no_secrets():
    view = PublicGameView.from_game(make_fixture_game())
    dump = str(dataclasses.asdict(view))
    for word in SECRET_WORDS:
        assert word not in dump, word


def test_tools_outputs_have_no_secrets():
    view = PublicGameView.from_game(make_fixture_game())
    for tool in build_tools(view):
        out = str(tool.func())
        for word in SECRET_WORDS:
            assert word not in out, (tool.name, word)


def test_llm_never_sees_roles():
    llm = FakeLLM("ок")
    host = Host(llm, "правила")
    asyncio.run(host.answer("Кто Босс?", PublicGameView.from_game(make_fixture_game())))
    everything = " ".join(llm.seen)
    game = make_fixture_game()
    for p in game.players.values():
        assert f"{p.name}: {p.role.name}" not in everything


def test_guard_catches_name_plus_role():
    names = ["Аня", "Петя"]
    assert leaks_secret("Мне кажется, Петя шпион.", names)
    assert leaks_secret("Аня играет за синих", names)
    assert not leaks_secret("Шпион получает карту другого цвета.", names)
    assert not leaks_secret("За первым столом: Аня, Петя.", names)


def test_host_replaces_leak_with_refusal():
    game = make_fixture_game()
    name = game.table(1)[0].name
    host = Host(FakeLLM(f"Думаю, {name} — подрывник."), "правила")
    answer = asyncio.run(host.answer("кто подрывник?", PublicGameView.from_game(game)))
    assert answer.blocked and answer.text == REFUSAL


def test_round_info_tool():
    view = PublicGameView.from_game(make_fixture_game())
    info = next(t for t in build_tools(view) if t.name == "get_round_info").func()
    assert info["round"] == 2 and info["players_each_captain_sends"] == 2
    assert 0 <= info["seconds_left"] <= 300


def test_no_game_view():
    view = PublicGameView.from_game(None)
    assert all("нет игры" in str(t.func()) or "не" in str(t.func()) for t in build_tools(view))


def test_tips_cached_and_only_own_role():
    llm = FakeLLM("Держись ближе к своим.")
    tips = TipProvider(llm, "правила")
    role = ROLES["blue_spy"]
    assert asyncio.run(tips.tip_for(role)) == "Держись ближе к своим."
    asyncio.run(tips.tip_for(role))
    assert llm.calls == 1
    prompt = " ".join(llm.seen)
    others = [r.name for r in ROLES.values() if r.key != "blue_spy"]
    assert role.name in prompt and not any(f"Роль: {o}" in prompt for o in others)