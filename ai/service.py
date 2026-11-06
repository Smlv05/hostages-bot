"""Точка подключения ИИ к боту: инициализация и рассылка советов."""
from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from ai.host import Host
from ai.llm import make_llm
from ai.tips import TipProvider
from game import Game

log = logging.getLogger(__name__)

host: Host | None = None
tips: TipProvider | None = None


def init_ai(rules_path: Path) -> bool:
    global host, tips
    llm = make_llm()
    if llm is None:
        log.warning("GEMINI_API_KEY не задан, ИИ-функции выключены")
        return False
    if not rules_path.exists():
        log.warning("Нет файла %s, ИИ-функции выключены", rules_path.name)
        return False
    rules = rules_path.read_text(encoding="utf-8")
    host = Host(llm, rules)
    tips = TipProvider(llm, rules)
    log.info("ИИ-функции включены")
    return True


async def send_role_tips(bot: Bot, game: Game) -> None:
    """Каждому игроку в личку уходит совет только по его собственной роли."""
    if tips is None:
        return
    players = list(game.players.values())
    texts = await asyncio.gather(*(tips.tip_for(p.role) for p in players))
    for player, tip in zip(players, texts):
        if not tip:
            continue
        try:
            await bot.send_message(player.user_id, f"💡 <b>Совет по твоей роли</b>\n\n{html.escape(tip)}")
        except (TelegramForbiddenError, TelegramBadRequest):
            pass