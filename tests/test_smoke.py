"""ЗОНА АРГЫНА.

Не unit-тесты — на пятичасовом хакатоне они не окупаются. Здесь проверка
того, что **сценарий проходит целиком**: ровно то, что будет делать
технический эксперт. Запускается без ключа, в демо-режиме.

    pytest -q

Добавляйте сюда по одному тесту на каждый новый шаг сценария. Если тест
красный — это не «потом», это стоп для команды.
"""
import os

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("DB_PATH", "data/test.db")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_ok(client):
    """Приложение поднимается и отвечает."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_works_without_api_key(client):
    """Требование п. 5.6.6: проверка без личных аккаунтов участников."""
    assert client.get("/api/health").json()["demo_mode"] is True


def test_generate_returns_text(client):
    """Основной вызов модели не падает и возвращает непустой ответ."""
    r = client.post("/api/generate", json={"prompt": "тест"})
    assert r.status_code == 200
    assert len(r.json()["text"]) > 0


def test_generate_rejects_empty_prompt(client):
    """Пустой ввод обрабатывается понятной ошибкой, а не пятисоткой."""
    assert client.post("/api/generate", json={"prompt": "   "}).status_code == 400


def test_result_survives_reload(client):
    """Сохранение работает: результат виден после повторного запроса."""
    created = client.post("/api/items", json={"title": "проверка", "payload": {"x": 1}})
    assert created.status_code == 200
    item_id = created.json()["id"]

    titles = [i["title"] for i in client.get("/api/items").json()]
    assert "проверка" in titles

    client.delete(f"/api/items/{item_id}")
    assert item_id not in [i["id"] for i in client.get("/api/items").json()]


def test_frontend_is_served(client):
    """Главная страница отдаётся и подключает стили и скрипт."""
    html = client.get("/").text
    assert "styles.css" in html
    assert "app.js" in html


# --------------------------------------------------------------------------
# Сюда Аргын дописывает проверки основного сценария продукта.
# Пример формы:
#
# def test_main_scenario(client):
#     r = client.post("/api/<ваш эндпоинт>", json={<ваш вход>})
#     assert r.status_code == 200
#     data = r.json()
#     assert <ключевое поле> in data
#     assert data[<поле>] != ""
# --------------------------------------------------------------------------
