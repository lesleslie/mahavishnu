#!/usr/bin/env python3
"""Generate a compatibility report artifact for ecosystem contract checks."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from mahavishnu.core.compatibility import build_contract_report, write_contract_report


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/ecosystem-contract-report.json"),
        help="Path to the JSON report file.",
    )
    return parser.parse_args()


async def main_async(output: Path) -> None:
    """Build and write the compatibility report."""
    report = await build_contract_report()
    write_contract_report(report, output)


def main() -> None:
    """Entry point."""
    args = parse_args()
    asyncio.run(main_async(args.output))


if __name__ == "__main__":
    main()
