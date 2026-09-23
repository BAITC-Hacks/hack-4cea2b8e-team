"""Конфигурация приложения. Всё через переменные окружения, см. .env.example"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- LLM ---
# Любой OpenAI-совместимый провайдер.
#   OpenAI:  https://api.openai.com/v1            + gpt-4o-mini   (основной)
#   NVIDIA:  https://integrate.api.nvidia.com/v1  + meta/llama-3.3-70b-instruct
# Ключ берётся из командных API-кредитов OpenAI (промокод от организаторов),
# НЕ из подписки ChatGPT Pro — она API-доступа не даёт.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("MODEL", "gpt-4o-mini")

# DEMO_MODE=1 -> приложение работает БЕЗ API-ключа, на заглушках.
# Это требование п. 5.6.6 Положения: эксперт должен проверить решение
# без личных аккаунтов участников.
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1" or not OPENAI_API_KEY

# --- Приложение ---
APP_NAME = os.getenv("APP_NAME", "HackAlem Starter")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "app.db"))
