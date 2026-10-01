PYTHON ?= python
.PHONY: harness test examples acceptance

harness:
	$(PYTHON) scripts/check_harness.py

test:
	$(PYTHON) -m pytest

examples:
	$(PYTHON) examples/unified_demo.py

acceptance: harness test examples
