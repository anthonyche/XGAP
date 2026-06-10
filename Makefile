.PHONY: harness test examples acceptance

harness:
	python scripts/check_harness.py

test:
	python -m pytest

examples:
	@if [ -f examples/core_algebra_demo.py ]; then python examples/core_algebra_demo.py; fi
	@if [ -f examples/plan_print_demo.py ]; then python examples/plan_print_demo.py; fi

acceptance: harness test examples
