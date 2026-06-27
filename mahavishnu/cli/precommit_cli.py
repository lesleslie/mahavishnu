"""CLI subcommand: ``mahavishnu precommit lock`` (Spec #2, Phase 1).

Locks a hypothesis before iteration 0 so downstream iterations can be
checked for silent claim drift via ``check_post_hoc``.

Example::

    mahavishnu precommit lock \\
        --claim "Will improve throughput by 10%" \\
        --falsify "throughput drops" --falsify "p99 > 200ms" \\
        --success "throughput up >=10%" --success "p99 < 150ms" \\
        --confidence 75 \\
        --verify-with "echo POST-RUN-CLAIM"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import typer

from mahavishnu.core.precommitment import (
    Hypothesis,
    HypothesisLock,
    InMemoryLockStore,
    compute_signature,
)


precommit_app = typer.Typer(help="Precommitment hypothesis lock (Spec #2)")


@precommit_app.command("lock")
def precommit_lock(
    claim: str = typer.Option(..., "--claim", "-c", help="Hypothesis claim to lock"),
    falsify: list[str] = typer.Option(
        ...,
        "--falsify",
        "-f",
        help=(
            "Falsification criterion (repeat for multiple). "
            "If any observed at verify time, the lock is broken."
        ),
    ),
    success: list[str] = typer.Option(
        ...,
        "--success",
        "-s",
        help="Success criterion (repeat for multiple).",
    ),
    confidence: int = typer.Option(
        ...,
        "--confidence",
        "-C",
        min=0,
        max=100,
        help="Confidence in the hypothesis (0..100).",
    ),
    verify_with: str = typer.Option(
        "",
        "--verify-with",
        "-V",
        help=(
            "Optional verify-token. The lock records this opaque string so "
            "post-hoc verifiers know which downstream tool will be used."
        ),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit structured JSON instead of human-readable text.",
    ),
) -> None:
    """Lock a hypothesis before iteration 0."""
    hypothesis = Hypothesis(
        claim=claim,
        falsification_criteria=tuple(falsify),
        success_criteria=tuple(success),
        confidence=confidence,
        locked_at=datetime.now(timezone.utc),
    )
    signature = compute_signature(hypothesis)
    lock = HypothesisLock(store=InMemoryLockStore())
    result = lock.lock(hypothesis)

    payload = {
        "lock_id": result.lock_id,
        "signature": signature,
        "confidence": confidence,
        "locked_at": hypothesis.locked_at.isoformat(),
        "claim": claim,
        "falsification_criteria": list(falsify),
        "success_criteria": list(success),
        "verify_with": verify_with,
        "stored_signature": result.signature,
    }

    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(f"Locked hypothesis: {result.lock_id}")
    typer.echo(f"  Claim:      {claim}")
    typer.echo(f"  Confidence: {confidence}")
    typer.echo(f"  Signature:  {result.signature}")
    typer.echo(f"  Locked at:  {hypothesis.locked_at.isoformat()}")
    if verify_with:
        typer.echo(f"  Verify-with: {verify_with}")


__all__ = ["precommit_app", "precommit_lock"]