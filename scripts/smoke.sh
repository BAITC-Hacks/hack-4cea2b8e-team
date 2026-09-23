#!/usr/bin/env bash
# Проверка «проект действительно поднимается с нуля».
# Гоняйте это в 17:00 — ровно то же самое сделает технический эксперт (п. 5.4.16).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Сборка образа"
docker build -t hackalem-app . >/dev/null

echo "==> Запуск контейнера (демо-режим, без ключа)"
CID=$(docker run -d -p 8000:8000 hackalem-app)
trap 'docker rm -f "$CID" >/dev/null' EXIT

echo "==> Ожидание /api/health"
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> /api/health"
curl -fsS http://localhost:8000/api/health
echo

echo "==> /api/generate"
curl -fsS -X POST http://localhost:8000/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"проверка"}'
echo

echo "==> Главная страница"
curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8000/

echo "✓ Smoke-тест пройден"
