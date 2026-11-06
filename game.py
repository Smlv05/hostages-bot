"""Логика игры «Заложники»: роли, колода, лобби, столы, капитаны, раунды, таймер."""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum

ALLOWED_SIZES = (8, 10)
TOTAL_ROUNDS = 4
# Сколько игроков каждый капитан отправляет за другой стол в раунде
HOSTAGES_PER_ROUND = {1: 2, 2: 2, 3: 1, 4: 1}
# Длительность раундов в секундах. ЗАГЛУШКА: поставь значения из своих правил
ROUND_SECONDS = {1: 300, 2: 300, 3: 300, 4: 300}


class Team(str, Enum):
    BLUE = "blue"
    RED = "red"

    @property
    def team_name(self) -> str:
        return "🔵 Синие" if self is Team.BLUE else "🔴 Красные"

    @property
    def color_name(self) -> str:
        return "🔵 синий" if self is Team.BLUE else "🔴 красный"


@dataclass(frozen=True)
class Role:
    key: str
    name: str
    team: Team        # за кого игрок играет на самом деле
    card_color: Team  # какого цвета его карта (у шпионов отличается)
    description: str


ROLES: dict[str, Role] = {r.key: r for r in [
    Role("boss", "Босс", Team.BLUE, Team.BLUE,
         "Главная роль синих. Победа связана с тем, где ты окажешься к концу игры."),
    Role("blue_spy", "Синий шпион", Team.BLUE, Team.RED,
         "Ты играешь за СИНИХ, но твоя карта КРАСНАЯ. Показав карту, будешь выглядеть как красный."),
    Role("blue_commissar", "Синий комиссар", Team.BLUE, Team.BLUE,
         "Один раз за игру можешь проверить карту одного игрока."),
    Role("blue_modest", "Синий Скромник", Team.BLUE, Team.BLUE,
         "Ты никогда не показываешь свою карту, даже если просят."),
    Role("blue_civilian", "Гражданский (мирный житель)", Team.BLUE, Team.BLUE,
         "Особых способностей нет. Помогай синим."),
    Role("bomber", "Подрывник", Team.RED, Team.RED,
         "Главная роль красных. Победа связана с тем, где ты окажешься к концу игры."),
    Role("red_spy", "Красный шпион", Team.RED, Team.BLUE,
         "Ты играешь за КРАСНЫХ, но твоя карта СИНЯЯ. Показав карту, будешь выглядеть как синий."),
    Role("red_commissar", "Красный комиссар", Team.RED, Team.RED,
         "Один раз за игру можешь проверить карту одного игрока."),
    Role("red_modest", "Красный Скромник", Team.RED, Team.RED,
         "Ты никогда не показываешь свою карту, даже если просят."),
    Role("red_civilian", "Гражданский (мирный житель)", Team.RED, Team.RED,
         "Особых способностей нет. Помогай красным."),
]}

# Уникальные роли — по одной на игру
UNIQUE_ROLES = [
    "boss", "blue_spy", "blue_commissar", "blue_modest",
    "bomber", "red_spy", "red_commissar", "red_modest",
]


def build_deck(size: int) -> list[Role]:
    """8 игроков — только уникальные роли; всё сверх 8 добивается мирными поровну."""
    if size not in ALLOWED_SIZES:
        raise ValueError(f"Поддерживается только {ALLOWED_SIZES} игроков, а не {size}")
    civilians_per_team = (size - len(UNIQUE_ROLES)) // 2
    keys = UNIQUE_ROLES + ["blue_civilian", "red_civilian"] * civilians_per_team
    return [ROLES[k] for k in keys]


@dataclass
class Player:
    user_id: int
    name: str
    role: Role | None = None
    table: int | None = None


@dataclass
class Game:
    chat_id: int
    host_id: int
    size: int
    players: dict[int, Player] = field(default_factory=dict)
    started: bool = False
    round: int = 0
    round_started_at: float | None = None
    captains: dict[int, int] = field(default_factory=dict)  # номер стола -> user_id капитана
    lobby_message_id: int | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def is_full(self) -> bool:
        return len(self.players) >= self.size

    def add_player(self, user_id: int, name: str) -> bool:
        if self.started or self.is_full or user_id in self.players:
            return False
        self.players[user_id] = Player(user_id, name)
        return True

    def remove_player(self, user_id: int) -> bool:
        if self.started:
            return False
        return self.players.pop(user_id, None) is not None

    def start(self) -> None:
        """Раздаёт роли случайно и случайно делит игроков на два стола поровну."""
        if len(self.players) != self.size:
            raise ValueError("Лобби ещё не заполнено")
        deck = build_deck(self.size)
        random.shuffle(deck)
        players = list(self.players.values())
        for player, role in zip(players, deck):
            player.role = role

        random.shuffle(players)
        half = self.size // 2
        for i, player in enumerate(players):
            player.table = 1 if i < half else 2
        self.started = True

    def table(self, number: int) -> list[Player]:
        return [p for p in self.players.values() if p.table == number]

    def set_captain(self, user_id: int) -> int | None:
        """Делает игрока капитаном его стола. Возвращает номер стола или None."""
        player = self.players.get(user_id)
        if not self.started or player is None or player.table is None:
            return None
        self.captains[player.table] = user_id
        return player.table

    def next_round(self) -> int | None:
        if not self.started or self.round >= TOTAL_ROUNDS:
            return None
        self.round += 1
        self.round_started_at = time.monotonic()
        return self.round

    def seconds_left(self) -> int | None:
        if not self.round or self.round_started_at is None:
            return None
        elapsed = time.monotonic() - self.round_started_at
        return max(0, int(ROUND_SECONDS[self.round] - elapsed))