# Top-level Makefile for Mahavishnu repo-wide checks.
#
# Req: REQ-007
#
# This file is intentionally minimal — the heavy lifting lives in
# scripts/ and the package's own tooling (crackerjack, pytest, etc.).
# The targets here exist to give CI a stable entry point and to wire
# the monthly Tier 2 / Phase D eligibility check.

.PHONY: help tier2-eligibility tier2-eligibility-dry

help:
	@echo "Mahavishnu top-level Makefile targets:"
	@echo "  tier2-eligibility      Run the Tier 2 / Phase D eligibility check (monthly CI)."
	@echo "  tier2-eligibility-dry  Same as above but always exits 0 (for local smoke testing)."

# Run the Tier 2 / Phase D eligibility check. Wired into monthly CI.
# Exit code 1 means a trigger fired without a follow-up plan; CI fails.
tier2-eligibility: # req: REQ-007
	uv run python scripts/feature_eligibility.py

# Dry run for local smoke testing. Always exits 0 regardless of trigger state.
tier2-eligibility-dry: # req: REQ-007
	uv run python scripts/feature_eligibility.py --dry-run
