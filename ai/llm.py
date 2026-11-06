"""Клиент LLM с вызовом функций. Сейчас Gemini; провайдера можно заменить, сохранив метод run."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Protocol

from ai.tools import Tool

log = logging.getLogger(__name__)

# Временные ошибки сервера: перегрузка (503), лимит (429), сбой (500)
RETRY_STATUS = {429, 500, 503}
ATTEMPTS_PER_MODEL = 2


@dataclass
class LLMResult:
    text: str
    tool_calls: list[str] = field(default_factory=list)


class LLM(Protocol):
    async def run(self, system: str, user: str, tools: list[Tool] | None = None) -> LLMResult: ...


class GeminiLLM:
    def __init__(self, api_key: str, model: str, fallback_model: str | None = None, max_steps: int = 4):
        from google import genai
        from google.genai import errors, types

        self._types = types
        self._errors = errors
        self._client = genai.Client(api_key=api_key)
        self.models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
        self.max_steps = max_steps

    async def _generate(self, contents, config):
        """Пробует основную модель, при перегрузке повторяет и переходит на запасную."""
        last_error = None
        for model in self.models:
            for attempt in range(ATTEMPTS_PER_MODEL):
                try:
                    return await self._client.aio.models.generate_content(
                        model=model, contents=contents, config=config,
                    )
                except self._errors.APIError as e:
                    if e.code not in RETRY_STATUS:
                        raise
                    last_error = e
                    log.warning("Модель %s ответила %s, попытка %d", model, e.code, attempt + 1)
                    await asyncio.sleep(2 * (attempt + 1))
        raise last_error

    async def run(self, system: str, user: str, tools: list[Tool] | None = None) -> LLMResult:
        types = self._types
        tools = tools or []
        by_name = {t.name: t for t in tools}
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description) for t in tools
            ])] if tools else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user)])]
        calls: list[str] = []

        for _ in range(self.max_steps):
            resp = await self._generate(contents, config)
            function_calls = resp.function_calls or []
            if not function_calls:
                return LLMResult((resp.text or "").strip(), calls)

            contents.append(resp.candidates[0].content)
            parts = []
            for fc in function_calls:
                calls.append(fc.name)
                tool = by_name.get(fc.name)
                result = tool.func() if tool else {"error": f"Нет функции {fc.name}"}
                parts.append(types.Part.from_function_response(name=fc.name, response=result))
            contents.append(types.Content(role="user", parts=parts))

        return LLMResult("", calls)


def make_llm() -> LLM | None:
    """Создаёт клиента из .env. Без ключа возвращает None, и ИИ-функции просто выключены."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return GeminiLLM(
        api_key=api_key,
        model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
        fallback_model=os.getenv("GEMINI_FALLBACK_MODEL"),
    )