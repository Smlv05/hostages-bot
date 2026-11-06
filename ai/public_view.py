"""Публичное состояние игры — единственное, что получает LLM.

Здесь нет и не должно быть ролей, настоящих команд и цветов карт.
LLM не может раскрыть то, чего никогда не видела.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field

from game import HOSTAGES_PER_ROUND, TOTAL_ROUNDS, Game


@dataclass(frozen=True)
class PublicGameView:
    phase: str                    # "no_game" | "lobby" | "playing"
    size: int | None = None
    players_joined: int = 0
    round: int = 0
    total_rounds: int = TOTAL_ROUNDS
    hostages_per_captain: int | None = None
    seconds_left: int | None = None
    tables: dict[int, list[str]] = field(default_factory=dict)
    captains: dict[int, str | None] = field(default_factory=dict)

    @property
    def player_names(self) -> list[str]:
        return [name for names in self.tables.values() for name in names]

    @classmethod
    def from_game(cls, game: Game | None) -> "PublicGameView":
        if game is None:
            return cls(phase="no_game")
        if not game.started:
            return cls(phase="lobby", size=game.size, players_joined=len(game.players))

        # Берём только имя и стол. Поле role не читаем нигде в этом файле.
        tables = {n: [html.unescape(p.name) for p in game.table(n)] for n in (1, 2)}
        captains = {}
        for n in (1, 2):
            uid = game.captains.get(n)
            captains[n] = html.unescape(game.players[uid].name) if uid in game.players else None
        return cls(
            phase="playing",
            size=game.size,
            players_joined=len(game.players),
            round=game.round,
            hostages_per_captain=HOSTAGES_PER_ROUND.get(game.round),
            seconds_left=game.seconds_left(),
            tables=tables,
            captains=captains,
        )