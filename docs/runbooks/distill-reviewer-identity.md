# Distill Reviewer Identity Trust Root

**Audit finding:** H6 (2026-06-26, Plan 5 trust model audit)
**Owner:** Mahavishnu Orchestration
**Status:** SHIPPED 2026-06-27

## Context

Plan 5 distilled workflows publication previously trusted whichever
string was in `$MAHAVISHNU_USER_ID` at the shell layer with no root of
trust. Anyone who could set that environment variable could publish
distilled workflows.

This runbook covers the H6 fix: `mahavishnu.distill.reviewer.ReviewerIdentity`
gates every distillation pass through an explicit trust root.

## How trust is established

The distiller resolves a reviewer through two environment variables:

| Variable | Required | Meaning |
|----------|----------|---------|
| `MAHAVISHNU_USER_ID` | **yes** | Canonical reviewer identity recorded as the publisher. |
| `MAHAVISHNU_PUBLISHER_ALLOWLIST` | recommended | Path to an allowlist file, OR an inline CSV. |

Resolution order:

1. **No `MAHAVISHNU_USER_ID`** → `ReviewerNotTrustedError`. A CLI flag
   (`--reviewer`) is recorded for forensic visibility but NEVER
   authorizes publication. Env wins.
1. **`MAHAVISHNU_USER_ID` + allowlist present + user listed** → ALLOWED.
1. **`MAHAVISHNU_USER_ID` + allowlist present + user NOT listed** →
   `ReviewerNotTrustedError` (MHV-483).
1. **`MAHAVISHNU_USER_ID` + allowlist missing or empty** →
   **bootstrap mode**: ALLOWED with WARNING + audit log entry.
1. Reserved for future RBAC: signed tokens from a configured trust
   root (placeholder).

## Allowlist file format

Newline-delimited usernames, one per line. Inline CSV (comma-separated)
is also accepted for ad-hoc use.

```text
# /etc/mahavishnu/publisher_allowlist.txt
alice
bob
# comments are not yet supported; lines beginning with # are NOT skipped
```

Inline CSV form:

```bash
export MAHAVISHNU_PUBLISHER_ALLOWLIST="alice,bob,carol"
```

## Bootstrap mode

When `MAHAVISHNU_PUBLISHER_ALLOWLIST` is unset, OR points at a missing
file, OR is empty, the distiller proceeds but emits:

- A `WARNING` log line via `mahavishnu.distill.reviewer` with the
  reviewer ID.
- An audit log entry tagged `extra={"audit": True}` for ingestion by
  the Dhara `audit_log` subscriber.

Bootstrap mode is the v1 behavior and is acceptable for
single-tenant / development use only. Operators MUST configure an
allowlist before promoting distillers to multi-tenant use.

## Diagnostic steps

### "ReviewerNotTrustedError" on a known-good reviewer

1. Confirm the operator's shell has `MAHAVISHNU_USER_ID` set:
   ```bash
   echo "$MAHAVISHNU_USER_ID"
   ```
1. Confirm `MAHAVISHNU_PUBLISHER_ALLOWLIST` resolves to a readable file
   or a valid inline CSV.
1. Compare the resolved user (trimmed) against the allowlist contents.
   Comparison is exact (case-sensitive, no normalization).

### Bootstrap warnings flooding the logs

This is expected when the allowlist has not been configured. Create the
allowlist file:

```bash
sudo install -d -m 0750 /etc/mahavishnu
sudo tee /etc/mahavishnu/publisher_allowlist.txt >/dev/null <<EOF
alice
bob
carol
EOF
sudo chmod 0640 /etc/mahavishnu/publisher_allowlist.txt
export MAHAVISHNU_PUBLISHER_ALLOWLIST=/etc/mahavishnu/publisher_allowlist.txt
```

### Audit log ingestion

The audit log entries emitted by `emit_audit_log` carry
`extra={"audit": True, "reviewer_id": ..., "decision_source": ..., "decision_allowed": ...}`. The Dhara `audit_log` subscriber ingests
these into the event bus; downstream consumers (Akosha anomaly
detection) can flag unexpected bootstrap-mode publication spikes.

## Rollback

The distiller accepts `reviewer=None` and skips the gate for back-compat.
To temporarily disable H6 in production:

```python
from mahavishnu.distill.distiller import distill_workflows
ids = distill_workflows(conn, reviewer=None)  # gate skipped
```

This is an emergency-only escape hatch; the audit still requires the
distiller to be called explicitly with `reviewer=None` and that choice
is visible in code review.

## Future work

- Signed-token verification (`ReviewerSource.SIGNED_TOKEN`) from a
  configured trust root (placeholder only — current implementation
  never selects this branch).
- Allowlist file glob expansion (`*.txt`) and comments (`#` prefix).
- Per-repository allowlists keyed by `MAHAVISHNU_REPO_ID`.
