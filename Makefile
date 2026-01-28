# Makefile

.PHONY: build cleanup db-import start stop migrate

build:
	docker-compose build

cleanup:
	if [ -n "$(shell docker images -q)" ]; then docker rmi $(shell docker images -q); else echo "No images to remove"; fi

db_create:
	docker-compose up -d bot
	docker-compose exec bot bash -c "python scripts/migrate.py upgrade"

start:
	docker-compose up -d

stop:
	docker-compose down

db_migrate:
	docker-compose exec bot bash -c "python scripts/migrate.py upgrade"

rails_logs:
	docker attach $$(docker ps -a -f name=gym_bot --format '{{.ID}}')

rails_console:
	docker-compose exec bot bash -c "python"

bundle_install:
	docker-compose exec bot bash -c "pip install -r requirements.txt"