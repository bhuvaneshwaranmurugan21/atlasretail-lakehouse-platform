.PHONY: test quality evidence clean

test:
	python -m pytest

quality:
	python -m ruff check .
	python -m mypy src
	python -m pytest

evidence:
	python -m atlasretail.cli simulate --output evidence/local/failure-lab.json

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
