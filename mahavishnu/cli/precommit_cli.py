"""Precommit CLI commands — async, D-LOCK backed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from dhara.lock.in_memory import InMemoryDharaLock
import typer

from mahavishnu.core.precommitment import (
    Hypothesis,
    HypothesisLock,
    SignatureMismatchError,
)

precommit_app = typer.Typer(help="Precommitment hypothesis lock CLI.")


def _make_lock() -> HypothesisLock:
    """Construct a D-LOCK backed HypothesisLock.

    Production wiring (out of scope for v1): instantiate the SQLBackendLock
    from a configured DharaSettings.storage_path. Tests use InMemoryDharaLock;
    CLI smoke runs use the in-memory impl by default.
    """
    return HypothesisLock(dhara_lock=InMemoryDharaLock())


@precommit_app.command("lock")
def precommit_lock(
    claim: str = typer.Option(...),
    falsification: list[str] = typer.Option(..., "--falsification"),
    success: list[str] = typer.Option(..., "--success"),
    confidence: int = typer.Option(..., min=0, max=100),
) -> None:
    async def _run() -> None:
        h = Hypothesis(
            claim=claim,
            falsification_criteria=tuple(falsification),
            success_criteria=tuple(success),
            confidence=confidence,
            locked_at=datetime.now(UTC),
        )
        lock = _make_lock()
        result = await lock.lock(h)
        typer.echo(f"Locked hypothesis: {result.lock_id}")
        typer.echo(f"Signature: {result.signature[:16]}...")

    asyncio.run(_run())


@precommit_app.command("verify")
def precommit_verify(lock_id: str = typer.Option(...)) -> None:
    async def _run() -> None:
        lock = _make_lock()
        ok = await lock.verify_lock(lock_id)
        typer.echo("valid" if ok else "not found")

    asyncio.run(_run())


@precommit_app.command("check-post-hoc")
def precommit_check_post_hoc(
    lock_id: str = typer.Option(...),
    observed_claim: str = typer.Option(...),
) -> None:
    async def _run() -> None:
        lock = _make_lock()
        try:
            await lock.check_post_hoc(lock_id, observed_claim=observed_claim)
            typer.echo("ok")
        except SignatureMismatchError as exc:
            typer.echo(f"signature mismatch: {exc.message}")

    asyncio.run(_run())
