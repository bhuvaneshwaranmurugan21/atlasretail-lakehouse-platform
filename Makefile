.PHONY: check evidence

check:
	ruff check .
	mypy src
	pytest

evidence:
	python -m atlasretail.cli simulate --output evidence/local-simulation.json

