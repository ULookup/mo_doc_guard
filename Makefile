.PHONY: setup run run-mcp lint test docker-up docker-down

setup:
	bash scripts/setup_dev.sh

run:
	python3 -m app.main

run-mcp:
	python3 -m uvicorn app.mcp_gateway.server:app --host 127.0.0.1 --port 8787

lint:
	python3 -m ruff check app

test:
	python3 -m pytest -q

docker-up:
	docker compose up --build

docker-down:
	docker compose down
