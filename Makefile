format:
	ruff check . --fix --config=pyproject.toml
	black . --config=pyproject.toml

check:
	mypy . --config=pyproject.toml

migrations:
	@docker compose exec -it backend bash -c "python manage.py makemigrations && python manage.py migrate"

tests:
	@pytest tests -v --ff

run:
	sudo docker compose -f docker-compose_dev.yml build --no-cache && sudo docker compose -f docker-compose_dev.yml up -d

.PHONY: format check migrations tests run