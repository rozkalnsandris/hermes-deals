SHELL := /bin/bash

.PHONY: up down logs migrate test probe verify clean

up:
	docker compose up -d db api web

down:
	docker compose down

logs:
	docker compose logs -f --tail=100 api web db

migrate:
	docker compose run --rm api alembic upgrade head

test:
	docker compose exec -T api python -m unittest discover -s tests -v

probe:
	docker compose run --rm worker python -m app.collector_cli probe --all

verify:
	./verify.sh

# Delete only generated code/test caches. Runtime evidence, databases,
# snapshots, audit artifacts and backups are deliberately out of scope.
clean:
	find backend tools -type f \( \
		-name '*.pyc' -o \
		-name '*.pyo' -o \
		-path '*/.pytest_cache/*' -o \
		-path '*/.mypy_cache/*' -o \
		-path '*/.ruff_cache/*' \
	\) -delete
	find backend tools -depth -type d \( \
		-name '__pycache__' -o \
		-name '.pytest_cache' -o \
		-name '.mypy_cache' -o \
		-name '.ruff_cache' \
	\) -empty -delete
