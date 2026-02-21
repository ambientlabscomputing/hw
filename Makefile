## setup: Install development dependencies
setup:
	pip install -r requirements.dev.txt

## test: Run tests with coverage
test:
	pytest -v --cov=src --cov-report=html

## lint: Run linters and formatters by triggering pre-commit hooks
lint:
	pre-commit run --all-files

## install: Install the package
install:
	pip install .

