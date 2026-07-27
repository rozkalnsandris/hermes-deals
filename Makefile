SHELL := /bin/bash

.PHONY: up down logs migrate test probe verify

up:
	docker compose up -d db api web

down:
	docker compose down

logs:
	docker compose logs -f --tail=100 api web db

migrate:
	docker compose run --rm api alembic upgrade head

test:
	docker compose run --rm api python -m unittest discover -s tests -v

probe:
	docker compose run --rm worker python -m app.collector_cli probe --all

verify:
	./verify.sh
