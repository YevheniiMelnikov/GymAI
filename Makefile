format:
	black . --config=project.toml
	isort . --settings-path project.toml

check:
	mypy . --config-file=project.toml
	flake8 . --config-file=project.toml

.PHONY: format check
