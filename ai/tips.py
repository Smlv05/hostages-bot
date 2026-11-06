"""Советы по роли в личку. LLM получает только роль самого игрока, без чужих данных."""
from __future__ import annotations

import logging

from ai.llm import LLM
from ai.prompts import build_tip_system
from game import Role

log = logging.getLogger(__name__)


def role_prompt(role: Role) -> str:
    return (
        f"Роль: {role.name}\n"
        f"Настоящая команда: {role.team.team_name}\n"
        f"Цвет карты: {role.card_color.color_name}\n"
        f"Описание роли: {role.description}\n"
        "Дай совет по стратегии для этой роли."
    )


class TipProvider:
    def __init__(self, llm: LLM, rules: str):
        self.llm = llm
        self.system = build_tip_system(rules)
        self._cache: dict[str, str] = {}  # ролей всего 10, экономим бесплатный лимит

    async def tip_for(self, role: Role) -> str | None:
        if role.key in self._cache:
            return self._cache[role.key]
        try:
            result = await self.llm.run(self.system, role_prompt(role))
        except Exception:
            log.exception("Не удалось получить совет для роли %s", role.key)
            return None
        tip = result.text.strip()
        if tip:
            self._cache[role.key] = tip
        return tip or None