.PHONY: setup run lint test docker-up docker-down

setup:
	bash scripts/setup_dev.sh

run:
	python -m app.main

lint:
	ruff check app

test:
	pytest -q

docker-up:
	docker compose up --build

docker-down:
	docker compose down
