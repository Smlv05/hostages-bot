"""Функции, которые LLM может вызвать. Все читают только PublicGameView."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ai.public_view import PublicGameView

NO_GAME = {"status": "В этом чате сейчас нет игры."}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    func: Callable[[], dict]


def build_tools(view: PublicGameView) -> list[Tool]:
    def lobby_status() -> dict:
        if view.phase == "no_game":
            return NO_GAME
        return {"phase": view.phase, "size": view.size, "players_joined": view.players_joined}

    def round_info() -> dict:
        if view.phase != "playing":
            return NO_GAME if view.phase == "no_game" else {"status": "Игра ещё не началась (идёт набор в лобби)."}
        if view.round == 0:
            return {"status": "Игра началась, но первый раунд ещё не запущен.", "total_rounds": view.total_rounds}
        return {
            "round": view.round,
            "total_rounds": view.total_rounds,
            "players_each_captain_sends": view.hostages_per_captain,
            "seconds_left": view.seconds_left,
        }

    def tables() -> dict:
        if view.phase != "playing":
            return {"status": "Столы ещё не сформированы."}
        result = {f"table_{n}": names for n, names in view.tables.items()}
        if view.round > 1:
            result["note"] = ("Это состав на момент раздачи карт. Бот не отслеживает переходы "
                              "между столами, текущий состав игроки знают сами.")
        return result

    def captains() -> dict:
        if view.phase != "playing":
            return {"status": "Капитанов пока нет: игра не началась."}
        return {f"table_{n}": name or "не назначен" for n, name in view.captains.items()}

    return [
        Tool("get_lobby_status", "Есть ли игра в чате, идёт ли набор, сколько игроков уже в лобби.", lobby_status),
        Tool("get_round_info",
             "Текущий раунд, всего раундов, сколько игроков каждый капитан отправляет "
             "за другой стол в этом раунде, сколько секунд осталось до конца раунда.", round_info),
        Tool("get_tables", "Состав столов на момент раздачи карт (только имена). Переходы бот не отслеживает.", tables),
        Tool("get_captains", "Кто капитан (лидер) каждого стола.", captains),
    ]