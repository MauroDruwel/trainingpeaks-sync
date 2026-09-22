.PHONY: install dev test sync daemon status clean

install:
	pip install .

dev:
	pip install -e ".[dev]"

test:
	pytest -v

test-cov:
	pytest --cov=src --cov-report=term-missing

sync:
	strava-sync sync --once

daemon:
	strava-sync sync --daemon

status:
	strava-sync status

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.log" -delete
	rm -rf .pytest_cache .coverage htmlcov build dist *.egg-info
