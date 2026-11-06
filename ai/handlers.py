"""Вопросы ИИ-ведущему: /ask в группе и в личке, реплаи боту в группе, обычный текст в личке."""
from __future__ import annotations

import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ai import service
from ai.public_view import PublicGameView
from game import Game

log = logging.getLogger(__name__)

GROUP = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
PRIVATE = F.chat.type == ChatType.PRIVATE
USER_COOLDOWN = 10  # секунд между вопросами одного игрока (бережём бесплатный лимит)


def build_ai_router(games: dict[int, Game]) -> Router:
    router = Router()
    last_ask: dict[tuple[int, int], float] = {}

    def game_for(message: Message) -> Game | None:
        """В группе — игра этого чата, в личке — игра, в которой участвует игрок."""
        if message.chat.type == ChatType.PRIVATE:
            return next((g for g in games.values() if message.from_user.id in g.players), None)
        return games.get(message.chat.id)

    async def handle_question(message: Message, bot: Bot, question: str) -> None:
        if service.host is None:
            await message.reply("ИИ-ведущий сейчас выключен.")
            return
        key = (message.chat.id, message.from_user.id)
        now = time.monotonic()
        if now - last_ask.get(key, 0) < USER_COOLDOWN:
            await message.reply("Подожди пару секунд перед следующим вопросом.")
            return
        last_ask[key] = now

        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        view = PublicGameView.from_game(game_for(message))
        try:
            answer = await service.host.answer(question, view)
        except Exception:
            log.exception("Ошибка LLM")
            await message.reply("Ведущий сейчас перегружен, попробуй через минуту.")
            return
        if answer.blocked:
            log.warning("Guard заблокировал ответ: %r", answer.raw_text)
        await message.reply("🤖 " + html.escape(answer.text))

    @router.message(Command("ask"))
    async def ask(message: Message, command: CommandObject, bot: Bot) -> None:
        question = (command.args or "").strip()
        if not question:
            await message.reply("Напиши вопрос после команды, например: /ask сколько игроков переходит в 4 раунде?")
            return
        await handle_question(message, bot, question)

    @router.message(GROUP, F.text, F.reply_to_message.from_user.is_bot)
    async def reply_to_bot(message: Message, bot: Bot) -> None:
        me = await bot.me()
        if message.reply_to_message.from_user.id != me.id or message.text.startswith("/"):
            return
        await handle_question(message, bot, message.text)

    @router.message(PRIVATE, F.text, ~F.text.startswith("/"))
    async def private_text(message: Message, bot: Bot) -> None:
        await handle_question(message, bot, message.text)

    return router