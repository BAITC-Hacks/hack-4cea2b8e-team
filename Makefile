.PHONY: install dev fast docker test smoke hour

install:      ## Поставить зависимости
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cp -n .env.example .env || true

dev:          ## Запустить основное приложение (http://localhost:8000)
	.venv/bin/uvicorn app.main:app --reload --port 8000

fast:         ## Запустить быстрый прототип на Streamlit (http://localhost:8501)
	.venv/bin/pip install streamlit -q && .venv/bin/streamlit run app_fast.py

docker:       ## Поднять через Docker (так проект будет проверять эксперт)
	docker compose up --build

test:         ## Прогнать тесты сценария
	.venv/bin/pytest -q

smoke:        ## Проверить, что проект поднимается с нуля
	./scripts/smoke.sh

hour:         ## Почасовой чекпойнт:  make hour M="что сделали"
	./scripts/hourly.sh "$(M)"
