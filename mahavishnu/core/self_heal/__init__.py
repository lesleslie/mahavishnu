"""Three-layer self-heal protocol (Spec #4, Phase 2).

Public surface:

- L1 (transient retry): ``l1_retry`` decorator-like async function with
  bounded attempts and exponential backoff. Raises ``L1RetryExhausted``
  when the budget is spent.
- L2 (no-op): ``L2Noop`` is a deterministic pass-through. The marker
  string is the regression pin that downstream callers depend on.
- L3 (rule extraction): ``extract_rule`` summarises a failure; the
  ``RuleStore`` is the in-memory v0 audit log. Dhara wiring follows
  when the ``self_heal_audit_log`` table is unblocked.

Substrate status: ``sql_blocked``. v0 is in-memory only.
"""

from __future__ import annotations

from mahavishnu.core.self_heal.l1_retry import (
    L1RetryExhausted,
    l1_retry,
)
from mahavishnu.core.self_heal.l2_noop import L2Noop
from mahavishnu.core.self_heal.l3_rule_store import (
    RuleRecord,
    RuleStore,
    apply_rule,
    extract_rule,
    record_rule,
)

__all__ = [
    "L1RetryExhausted",
    "L2Noop",
    "RuleRecord",
    "RuleStore",
    "apply_rule",
    "extract_rule",
    "l1_retry",
    "record_rule",
]