"""Последний фильтр перед отправкой в общий чат.

LLM не видит ролей, но может их «угадать». Если в одном предложении встречаются
имя игрока и слово про роль или команду, ответ заменяется отказом.
"""
from __future__ import annotations

import re

ROLE_WORDS = re.compile(
    r"босс|подрывник|шпион|комиссар|скромник|мирн|гражданск"
    r"|за синих|за красных|синей команд|красной команд|синих команд|красных команд"
    r"|(син|красн)\w*\s+карт",
    re.IGNORECASE,
)
SENTENCE_SPLIT = re.compile(r"[.!?\n]+")


def leaks_secret(text: str, player_names: list[str]) -> bool:
    names = [n.casefold() for n in player_names if len(n.strip()) >= 2]
    if not names:
        return False
    for sentence in SENTENCE_SPLIT.split(text):
        low = sentence.casefold()
        if ROLE_WORDS.search(low) and any(name in low for name in names):
            return True
    return False