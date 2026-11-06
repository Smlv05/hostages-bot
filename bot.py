"""Telegram-бот для игры «Заложники»."""
import asyncio
import html
import logging
import os
import socket
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from ai.handlers import build_ai_router
from ai.service import init_ai, send_role_tips
from game import ALLOWED_SIZES, HOSTAGES_PER_ROUND, ROLES, ROUND_SECONDS, TOTAL_ROUNDS, Game, Player, Team

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_DIR = Path(__file__).parent
CARDS_DIR = BASE_DIR / "cards"

router = Router()
games: dict[int, Game] = {}  # chat_id группы -> игра

GROUP = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
PRIVATE = F.chat.type == ChatType.PRIVATE
HOSTAGE_WORDS = {2: "двух игроков", 1: "одного игрока"}


# ---------- вспомогательное ----------

def find_player(user_id: int) -> tuple[Game | None, Player | None]:
    for game in games.values():
        if user_id in game.players:
            return game, game.players[user_id]
    return None, None


def lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Войти", callback_data="join"),
         InlineKeyboardButton(text="🚪 Выйти", callback_data="leave")],
        [InlineKeyboardButton(text="❌ Отменить игру", callback_data="cancel")],
    ])


def lobby_text(game: Game, bot_username: str) -> str:
    lines = [f"<b>🎭 Лобби «Заложники»</b> — {len(game.players)}/{game.size}", ""]
    if game.players:
        lines += [f"{i}. {p.name}" for i, p in enumerate(game.players.values(), 1)]
    else:
        lines.append("<i>Пока никого…</i>")
    if game.started:
        lines += ["", "✅ Лобби заполнено, игра началась!"]
    else:
        lines += ["", f"Перед входом открой <a href=\"https://t.me/{bot_username}?start=go\">личку с ботом</a> "
                      "и нажми Start, иначе он не сможет прислать тебе роль."]
    return "\n".join(lines)


def role_text(player: Player) -> str:
    role = player.role
    return (
        f"🎭 <b>Твоя роль: {role.name}</b>\n\n"
        f"Твоя команда: <b>{role.team.team_name}</b>\n"
        f"Цвет твоей карты: <b>{role.card_color.color_name}</b>\n"
        f"Твой стол: <b>{player.table}</b>\n\n"
        f"{role.description}\n\n"
        "🤫 Никому не пересылай это сообщение."
    )


def roles_text() -> str:
    lines = ["<b>📖 Роли в игре «Заложники»</b>", ""]
    for team in (Team.BLUE, Team.RED):
        lines.append(f"<b>{team.team_name}</b>")
        for role in ROLES.values():
            if role.team is not team:
                continue
            extra = " (только в игре на 10)" if "civilian" in role.key else ""
            card = "" if role.card_color is role.team else f", карта {role.card_color.color_name}"
            lines.append(f"• <b>{role.name}</b>{extra}{card}: {role.description}")
        lines.append("")
    return "\n".join(lines)


async def send_role(bot: Bot, player: Player) -> bool:
    text = role_text(player)
    photo = next((CARDS_DIR / f"{player.role.key}{ext}" for ext in (".jpg", ".jpeg", ".png")
                  if (CARDS_DIR / f"{player.role.key}{ext}").exists()), None)
    try:
        if photo:
            await bot.send_photo(player.user_id, FSInputFile(photo), caption=text)
        else:
            await bot.send_message(player.user_id, text)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


async def refresh_lobby(bot: Bot, game: Game) -> None:
    me = await bot.me()
    try:
        await bot.edit_message_text(
            lobby_text(game, me.username),
            chat_id=game.chat_id,
            message_id=game.lobby_message_id,
            reply_markup=None if game.started else lobby_keyboard(),
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        pass  # сообщение не изменилось или удалено


async def is_host_or_admin(bot: Bot, game: Game, user_id: int) -> bool:
    if user_id == game.host_id:
        return True
    member = await bot.get_chat_member(game.chat_id, user_id)
    return member.status in ("creator", "administrator")


async def launch_game(bot: Bot, game: Game) -> None:
    failed = [p.name for p in game.players.values() if not await send_role(bot, p)]

    lines = ["🎬 <b>Игра началась!</b> Роли отправлены каждому в личку.", ""]
    for number in (1, 2):
        lines.append(f"🚪 <b>Стол {number}:</b>")
        lines += [f"• {p.name}" for p in game.table(number)]
        lines.append("")
    lines.append("Назначьте капитанов: хост отвечает на сообщение игрока командой /captain.")
    lines.append("Раунды хост запускает командой /round. Вопросы ведущему: /ask")
    await bot.send_message(game.chat_id, "\n".join(lines))

    if failed:
        await bot.send_message(
            game.chat_id,
            "⚠️ Не смог отправить роль: " + ", ".join(failed)
            + "\nПусть откроют личку с ботом и напишут там /myrole",
        )
    await send_role_tips(bot, game)


# ---------- личка ----------

@router.message(CommandStart(), PRIVATE)
async def start_private(message: Message) -> None:
    await message.answer(
        "Привет! Я веду игру «Заложники» 🎭\n\n"
        "Добавь меня в группу и напиши там /newgame 8 или /newgame 10.\n"
        "Когда лобби заполнится, твоя роль придёт сюда.\n"
        "/myrole — прислать роль ещё раз.\n"
        "/roles — описание всех ролей."
    )


@router.message(Command("myrole"), PRIVATE)
async def my_role(message: Message, bot: Bot) -> None:
    game, player = find_player(message.from_user.id)
    if not player or not game.started:
        await message.answer("Ты сейчас не участвуешь в начавшейся игре.")
        return
    await send_role(bot, player)


@router.message(Command("roles"))
async def roles(message: Message) -> None:
    await message.answer(roles_text())


@router.message(Command("newgame", "round", "endgame", "captain"), PRIVATE)
async def group_only(message: Message) -> None:
    await message.answer("Эта команда работает только в группе.")


# ---------- группа ----------

@router.message(Command("help"), GROUP)
async def group_help(message: Message) -> None:
    await message.answer(
        "<b>Команды:</b>\n"
        "/newgame 8 или /newgame 10 — создать лобби\n"
        "/captain — ответом на сообщение игрока: назначить его капитаном стола (хост)\n"
        "/round — следующий раунд (хост)\n"
        "/endgame — завершить игру и раскрыть роли (хост или админ)\n"
        "/ask вопрос — спросить ИИ-ведущего о правилах и ходе игры\n"
        "/roles — описание всех ролей\n"
        "/myrole — в личке с ботом, прислать роль ещё раз"
    )


@router.message(Command("newgame"), GROUP)
async def new_game(message: Message, command: CommandObject, bot: Bot) -> None:
    chat_id = message.chat.id
    if chat_id in games:
        await message.reply("В этом чате уже идёт игра. Завершить её: /endgame")
        return
    try:
        size = int((command.args or "").strip())
    except ValueError:
        size = 0
    if size not in ALLOWED_SIZES:
        await message.reply("Укажи число игроков: /newgame 8 или /newgame 10")
        return

    game = Game(chat_id=chat_id, host_id=message.from_user.id, size=size)
    games[chat_id] = game
    me = await bot.me()
    lobby = await message.answer(lobby_text(game, me.username), reply_markup=lobby_keyboard(),
                                 disable_web_page_preview=True)
    game.lobby_message_id = lobby.message_id


@router.callback_query(F.data == "join")
async def join(cb: CallbackQuery, bot: Bot) -> None:
    chat_id = cb.message.chat.id
    game = games.get(chat_id)
    user = cb.from_user
    if not game or game.started:
        await cb.answer("Лобби уже закрыто.", show_alert=True)
        return
    if user.id in game.players:
        await cb.answer("Ты уже в лобби.")
        return
    other_game, _ = find_player(user.id)
    if other_game:
        await cb.answer("Ты уже играешь в другом чате.", show_alert=True)
        return

    # Проверяем, что бот может писать игроку в личку
    try:
        title = html.escape(cb.message.chat.title or "группа")
        await bot.send_message(user.id, f"Ты в лобби «Заложников» ({title}). Жди начала игры.")
    except (TelegramForbiddenError, TelegramBadRequest):
        me = await bot.me()
        await cb.answer(f"Сначала открой личку с @{me.username}, нажми Start и снова «Войти».",
                        show_alert=True)
        return

    async with game.lock:
        if games.get(chat_id) is not game or not game.add_player(user.id, html.escape(user.full_name)):
            await cb.answer("Не получилось: лобби заполнено или закрыто.", show_alert=True)
            return
        just_filled = game.is_full
        if just_filled:
            game.start()

    await cb.answer("Ты в игре!")
    await refresh_lobby(bot, game)
    if just_filled:
        await launch_game(bot, game)


@router.callback_query(F.data == "leave")
async def leave(cb: CallbackQuery, bot: Bot) -> None:
    game = games.get(cb.message.chat.id)
    if not game:
        await cb.answer("Лобби не найдено.")
        return
    async with game.lock:
        removed = game.remove_player(cb.from_user.id)
    if not removed:
        await cb.answer("Тебя нет в лобби (или игра уже началась).")
        return
    await cb.answer("Ты вышел из лобби.")
    await refresh_lobby(bot, game)


@router.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, bot: Bot) -> None:
    game = games.get(cb.message.chat.id)
    if not game:
        await cb.answer("Лобби не найдено.")
        return
    if not await is_host_or_admin(bot, game, cb.from_user.id):
        await cb.answer("Отменить может только хост или админ.", show_alert=True)
        return
    games.pop(game.chat_id, None)
    await cb.answer("Игра отменена.")
    await cb.message.edit_text("❌ Лобби отменено.")


@router.message(Command("captain"), GROUP)
async def set_captain(message: Message) -> None:
    game = games.get(message.chat.id)
    if not game or not game.started:
        await message.reply("Игра ещё не началась.")
        return
    if message.from_user.id != game.host_id:
        await message.reply("Капитанов назначает хост игры.")
        return
    if not message.reply_to_message:
        await message.reply("Ответь этой командой на сообщение игрока, которого назначаешь капитаном.")
        return
    target = message.reply_to_message.from_user
    table = game.set_captain(target.id)
    if table is None:
        await message.reply("Этот человек не играет в текущей игре.")
        return
    await message.answer(f"👑 {game.players[target.id].name} — капитан стола {table}.")


@router.message(Command("round"), GROUP)
async def next_round(message: Message) -> None:
    game = games.get(message.chat.id)
    if not game or not game.started:
        await message.reply("Игра ещё не началась.")
        return
    if message.from_user.id != game.host_id:
        await message.reply("Раунды переключает только хост игры.")
        return
    number = game.next_round()
    if number is None:
        await message.reply("Все 4 раунда сыграны. Подведите итог и завершите игру: /endgame")
        return
    minutes, seconds = divmod(ROUND_SECONDS[number], 60)
    await message.answer(
        f"⏱ <b>Раунд {number} из {TOTAL_ROUNDS}</b> ({minutes}:{seconds:02d})\n"
        f"Каждый капитан отправляет за противоположный стол <b>{HOSTAGE_WORDS[HOSTAGES_PER_ROUND[number]]}</b>."
    )


@router.message(Command("endgame"), GROUP)
async def end_game(message: Message, bot: Bot) -> None:
    game = games.get(message.chat.id)
    if not game:
        await message.reply("Активной игры нет.")
        return
    if not await is_host_or_admin(bot, game, message.from_user.id):
        await message.reply("Завершить игру может только хост или админ.")
        return
    games.pop(game.chat_id, None)
    if not game.started:
        await message.answer("Лобби закрыто.")
        return
    lines = ["🏁 <b>Игра окончена!</b> Кто кем был:", ""]
    for p in sorted(game.players.values(), key=lambda p: (p.role.team.value, p.role.name)):
        lines.append(f"• {p.name} — {p.role.name} ({p.role.team.team_name}), стол {p.table}")
    await message.answer("\n".join(lines))


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Не найден BOT_TOKEN. Создай файл .env с BOT_TOKEN=...")
    logging.basicConfig(level=logging.INFO)
    init_ai(BASE_DIR / "rules.md")

    session = AiohttpSession()
    session._connector_init["family"] = socket.AF_INET  # только IPv4
    bot = Bot(BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="newgame", description="Создать лобби: /newgame 8 или 10"),
        BotCommand(command="captain", description="Назначить капитана (ответом на сообщение)"),
        BotCommand(command="round", description="Следующий раунд"),
        BotCommand(command="ask", description="Спросить ИИ-ведущего"),
        BotCommand(command="endgame", description="Завершить игру и раскрыть роли"),
        BotCommand(command="roles", description="Какая роль что делает"),
        BotCommand(command="myrole", description="Прислать мою роль (в личке)"),
        BotCommand(command="help", description="Список команд"),
    ])
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(build_ai_router(games))
    await dp.start_polling(bot)


if __name__ == "__main__":
    if sys.platform == "win32":
        # На Windows стандартный цикл (Proactor) иногда рвёт соединения
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())