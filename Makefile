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


.PHONY: format check migrations tests