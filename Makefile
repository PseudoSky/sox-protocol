# SOX Protocol — top-level Makefile
# Most targets delegate to the Python package.

PYTHON_PKG := packages/python
SPEC_SCHEMAS := spec/schemas

.PHONY: codegen test lint typecheck import-lint ci

# ---------------------------------------------------------------------------
# codegen — regenerate Python types from spec/schemas/
# ---------------------------------------------------------------------------
# Requires: datamodel-codegen (install via: uv tool install datamodel-code-generator)
#
# Outputs to packages/python/src/sox_protocol/core/enforcer/events.py.
# The generated file carries "DO NOT EDIT BY HAND" and is checked in.
codegen:
	@echo "==> Regenerating Python types from spec/schemas/ ..."
	datamodel-codegen \
		--input $(SPEC_SCHEMAS)/event.schema.json \
		--input $(SPEC_SCHEMAS)/decision.schema.json \
		--input-file-type jsonschema \
		--output $(PYTHON_PKG)/src/sox_protocol/core/enforcer/_generated_raw.py \
		--output-model-type dataclasses.dataclass \
		--target-python-version 3.11 \
		--use-standard-collections \
		--use-union-operator \
		--formatters ruff_format ruff_check
	@python3 scripts/patch_codegen_header.py \
		$(PYTHON_PKG)/src/sox_protocol/core/enforcer/_generated_raw.py \
		$(PYTHON_PKG)/src/sox_protocol/core/enforcer/events.py
	@rm -f $(PYTHON_PKG)/src/sox_protocol/core/enforcer/_generated_raw.py
	@echo "==> Done. Review $(PYTHON_PKG)/src/sox_protocol/core/enforcer/events.py"

# ---------------------------------------------------------------------------
# test — run pytest with coverage
# ---------------------------------------------------------------------------
test:
	cd $(PYTHON_PKG) && \
		python -m pytest tests/unit/ \
			--cov=sox_protocol.core.enforcer.decide \
			--cov-report=term-missing \
			--cov-fail-under=100 \
			-v

# ---------------------------------------------------------------------------
# lint — ruff
# ---------------------------------------------------------------------------
lint:
	cd $(PYTHON_PKG) && python -m ruff check src/ tests/

# ---------------------------------------------------------------------------
# typecheck — mypy --strict on core/
# ---------------------------------------------------------------------------
typecheck:
	cd $(PYTHON_PKG) && python -m mypy --strict src/sox_protocol/core/

# ---------------------------------------------------------------------------
# import-lint — enforce core/ does not import adapters/
# ---------------------------------------------------------------------------
import-lint:
	cd $(PYTHON_PKG) && python -m lint-imports

# ---------------------------------------------------------------------------
# ci — run all checks
# ---------------------------------------------------------------------------
ci: lint typecheck import-lint test
