# SOX Protocol — top-level Makefile
# Most targets delegate to the Python package.

PYTHON_PKG := packages/python
SPEC_SCHEMAS := spec/schemas

.PHONY: codegen test lint typecheck import-lint ci demo demo-broadcast test-integration

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
# demo — run the two-agent-clarification demo end-to-end
#
# Requires: pip install -e packages/python[dev]   (or: pip install sox-protocol)
# No Claude API key needed: runs entirely in-process with SQLite.
# ---------------------------------------------------------------------------
demo:
	@echo "==> Running DEMO-001: two-agent-clarification ..."
	python examples/two-agent-clarification/run_demo.py

# ---------------------------------------------------------------------------
# demo-broadcast — run the group-broadcast demo end-to-end
# ---------------------------------------------------------------------------
demo-broadcast:
	@echo "==> Running DEMO-002: group-broadcast ..."
	python examples/group-broadcast/run_demo.py

# ---------------------------------------------------------------------------
# test-integration — run M7 integration tests (CI-safe, no LLM API needed)
#
# Uses recorded/in-process responses via FastMCP's in-process Client harness.
# No network access required. Runs on Python 3.11+ (Linux and macOS).
# ---------------------------------------------------------------------------
test-integration:
	@echo "==> Running M7 integration tests ..."
	cd $(PYTHON_PKG) && \
		python -m pytest tests/integration/test_two_agent_exchange.py \
			-v \
			--tb=short

# ---------------------------------------------------------------------------
# ci — run all checks
# ---------------------------------------------------------------------------
ci: lint typecheck import-lint test test-integration
