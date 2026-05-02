.PHONY: test lint typecheck check benchmark

test:
	python -m pytest

lint:
	python -m ruff check .

typecheck:
	python -m mypy src

check: lint typecheck test

benchmark:
	python scripts/eval_p2.py --reingest
	python scripts/eval_p3.py
	python scripts/eval_p4.py --judge none
	python scripts/eval_p5.py --judge none
	python scripts/eval_p6.py --judge none
