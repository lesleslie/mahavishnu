#!/usr/bin/env python3
"""Regenerate evidence metrics block in docs/CRITICAL_REVIEW_2026.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "CRITICAL_REVIEW_2026.md"
START = "<!-- REVIEW_METRICS_START -->"
END = "<!-- REVIEW_METRICS_END -->"

ADAPTERS = [
    ROOT / "mahavishnu" / "engines" / "prefect_adapter.py",
    ROOT / "mahavishnu" / "engines" / "agno_adapter.py",
]

TODO_PAT = re.compile(r"\b(TODO|FIXME|XXX|HACK|WIP)\b")


@dataclass
class Metrics:
    generated_at: str
    todo_markers: int
    adapter_lines: list[tuple[str, int]]


def count_todo_markers(root: Path) -> int:
    count = 0
    for path in root.rglob("*.py"):
        if "/.venv/" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            if TODO_PAT.search(line):
                count += 1
    return count


def count_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except Exception:
        return 0


def build_metrics() -> Metrics:
    adapter_lines = [(str(p.relative_to(ROOT)), count_lines(p)) for p in ADAPTERS]
    todo_markers = count_todo_markers(ROOT / "mahavishnu")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return Metrics(
        generated_at=generated_at,
        todo_markers=todo_markers,
        adapter_lines=adapter_lines,
    )


def render_block(metrics: Metrics) -> str:
    lines = [
        START,
        f"Generated: {metrics.generated_at}",
        "",
        "Adapter Line Counts:",
        "",
    ]
    for path, count in metrics.adapter_lines:
        lines.append(f"- {path}: {count}")
    lines.extend(
        [
            "",
            f"TODO/FIXME/XXX/HACK/WIP markers in mahavishnu/: {metrics.todo_markers}",
            END,
        ]
    )
    return "\n".join(lines)


def update_doc(doc_path: Path, block: str) -> None:
    text = doc_path.read_text(encoding="utf-8")
    if START in text and END in text:
        pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
        new_text = pattern.sub(block, text)
    else:
        new_text = text.rstrip() + "\n\n" + block + "\n"
    doc_path.write_text(new_text, encoding="utf-8")


def main() -> None:
    metrics = build_metrics()
    block = render_block(metrics)
    update_doc(DOC_PATH, block)


if __name__ == "__main__":
    main()
