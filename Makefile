.PHONY: test quality evidence clean

test:
	python -m pytest

quality:
	python -m ruff check .
	python -m mypy src release/part4/stage8 release/part5/stage1
	python scripts/validate_part4_contract.py
	python scripts/validate_part4_sources.py
	python scripts/validate_part4_admission_controls.py
	python scripts/validate_part4_stage4_controls.py
	python scripts/validate_part4_stage5_controls.py
	python scripts/validate_part4_stage6_controls.py
	python scripts/verify_part4_stage7_runtime.py
	python -m release.part4.stage8.validate_controls
	python -m release.part5.stage1.validate_controls
	python -m pytest

evidence:
	python -m atlasretail.cli simulate --output evidence/local/failure-lab.json

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
