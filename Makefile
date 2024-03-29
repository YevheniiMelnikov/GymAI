format:
	black . --config=project.toml
	isort . --settings-path project.toml

check:
	mypy . --config-file=project.toml
	flake8 . --config-file=project.toml

migrations:
	@docker compose exec -it backend bash -c "python manage.py makemigrations && python manage.py migrate"


.PHONY: format check
