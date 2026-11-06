"""ИИ-ведущий: отвечает на вопросы по правилам и о публичном состоянии игры."""
from __future__ import annotations

from dataclasses import dataclass, field

from ai.guard import leaks_secret
from ai.llm import LLM
from ai.prompts import REFUSAL, build_host_system
from ai.public_view import PublicGameView
from ai.tools import build_tools

MAX_QUESTION_LEN = 500
EMPTY_ANSWER = "Не получилось ответить, попробуй переформулировать вопрос."


@dataclass
class HostAnswer:
    text: str
    raw_text: str
    tool_calls: list[str] = field(default_factory=list)
    blocked: bool = False  # True, если guard заменил ответ отказом


class Host:
    def __init__(self, llm: LLM, rules: str):
        self.llm = llm
        self.system = build_host_system(rules)

    async def answer(self, question: str, view: PublicGameView) -> HostAnswer:
        result = await self.llm.run(self.system, question[:MAX_QUESTION_LEN], build_tools(view))
        raw = result.text.strip()
        if not raw:
            return HostAnswer(EMPTY_ANSWER, raw, result.tool_calls)
        if leaks_secret(raw, view.player_names):
            return HostAnswer(REFUSAL, raw, result.tool_calls, blocked=True)
        return HostAnswer(raw, raw, result.tool_calls)