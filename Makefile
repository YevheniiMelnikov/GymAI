format:
	ruff check --select I . --fix --config=pyproject.toml
	ruff check --select E . --fix --config=pyproject.toml
	ruff check --select F . --fix --config=pyproject.toml
	ruff check --select B . --fix --config=pyproject.toml
	ruff check --select A . --fix --config=pyproject.toml
	black .

check:
	ruff check . --fix --config=pyproject.toml

migrations:
	@docker compose exec -it backend bash -c "python manage.py makemigrations && python manage.py migrate"

tests:
	@pytest tests -v --ff

run:
	sudo docker compose -f docker-compose_dev.yml build --no-cache && sudo docker compose -f docker-compose_dev.yml up -d

.PHONY: format check migrations tests run