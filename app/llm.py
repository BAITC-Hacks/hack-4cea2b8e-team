"""Тонкий слой над LLM.

Зачем отдельный модуль:
  1. DEMO_MODE — решение запускается и демонстрируется без ключа (п. 5.6.6).
  2. Лог всех вызовов в SQLite — это ваш «подтверждаемый прогресс» и материал
     для слайда про архитектуру.
  3. Смена провайдера = одна переменная окружения, а не переписывание кода.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

from . import config
from .db import log_llm_call

_client = None


def _parse_json(raw: str) -> dict[str, Any]:
    """Терпимый разбор JSON: модели любят заворачивать ответ в ```json ... ```."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=config.OPENAI_API_KEY or "demo",
            base_url=config.OPENAI_BASE_URL,
        )
    return _client


# --------------------------------------------------------------------------
# Заглушки для DEMO_MODE. Замените на правдоподобные для вашей задачи ответы —
# именно их увидит технический эксперт, запускающий проект без ключа.
# --------------------------------------------------------------------------
DEMO_TEXT = (
    "[DEMO MODE] Это заглушка ответа модели. Приложение работает без API-ключа, "
    "чтобы проверяющий мог запустить основной сценарий. Задайте OPENAI_API_KEY "
    "в .env и перезапустите — ответы станут настоящими."
)

DEMO_JSON: dict[str, Any] = {
    "title": "Пример результата",
    "summary": "Краткое описание, сгенерированное в демо-режиме.",
    "tags": ["demo", "hackalem", "placeholder"],
    "score": 0.87,
}


def complete(
    prompt: str,
    system: str = "Ты — полезный ассистент. Отвечай кратко и по делу.",
    *,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """Обычный текстовый ответ."""
    started = time.time()
    if config.DEMO_MODE:
        out = DEMO_TEXT
    else:
        resp = _get_client().chat.completions.create(
            model=config.MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        out = resp.choices[0].message.content or ""
    log_llm_call("complete", prompt, out, time.time() - started, config.DEMO_MODE)
    return out


def complete_json(
    prompt: str,
    schema: dict[str, Any],
    system: str = "Верни строго валидный JSON по заданной схеме.",
    *,
    demo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Структурированный ответ. schema — JSON Schema объекта.

    Пример:
        complete_json("Разбери бриф", {
            "type": "object",
            "properties": {"title": {"type": "string"},
                           "tags": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "tags"],
            "additionalProperties": False,
        })
    """
    started = time.time()
    if config.DEMO_MODE:
        out = demo if demo is not None else DEMO_JSON
    else:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        try:
            # Строгий режим — поддерживается моделями OpenAI.
            resp = _get_client().chat.completions.create(
                model=config.MODEL,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": schema, "strict": True},
                },
            )
            out = _parse_json(resp.choices[0].message.content or "{}")
        except Exception:
            # Фолбэк: не все OpenAI-совместимые провайдеры (в т.ч. часть моделей
            # на NVIDIA NIM) принимают json_schema. Просим JSON промптом.
            messages[0] = {
                "role": "system",
                "content": (
                    system
                    + "\nОтветь ТОЛЬКО валидным JSON без markdown-обёртки, "
                    + "строго по схеме:\n"
                    + json.dumps(schema, ensure_ascii=False)
                ),
            }
            resp = _get_client().chat.completions.create(
                model=config.MODEL,
                messages=messages,
                response_format={"type": "json_object"},
            )
            out = _parse_json(resp.choices[0].message.content or "{}")
    log_llm_call("json", prompt, json.dumps(out, ensure_ascii=False),
                 time.time() - started, config.DEMO_MODE)
    return out


def stream(
    prompt: str,
    system: str = "Ты — полезный ассистент.",
) -> Iterator[str]:
    """Потоковый ответ — для живого демо это выглядит заметно убедительнее."""
    if config.DEMO_MODE:
        for word in DEMO_TEXT.split(" "):
            yield word + " "
            time.sleep(0.03)
        return
    resp = _get_client().chat.completions.create(
        model=config.MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        stream=True,
    )
    for chunk in resp:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
