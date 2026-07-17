"""C1.2 orphan sweep: prepend YAML frontmatter to 18 docs/plans files.

User-authorized (consented via AskUserQuestion on 2026-07-16). Mechanical.
Reads each file, prepends a uniform frontmatter block + adds a trailing HTML
legacy comment on the existing Status line so the validator's --allow-nonstandard
mode stays green.
"""
from pathlib import Path

PLAN_FM_TEMPLATE = (
    "---\n"
    "status: {status}\n"
    "role: {role}\n"
    "date: 2026-07-16\n"
    "last_reviewed: 2026-07-16\n"
    "superseded_by: null\n"
    "blocks_on: []\n"
    "topic: {topic}\n"
    "---\n"
    "\n"
)

# Per-file status / role / topic assignment, derived from each file's body.
ASSIGNMENTS = {
    "docs/plans/2026-05-07-unified-config-design.md":
        ("active", "canonical", "mcp-design"),
    "docs/plans/2026-07-16-dlq-fail-closed-wiring.md":
        ("shipped", "implementation", "persistence"),
    "docs/plans/PREFECT_ADAPTER_COMPLETION_PLAN.md":
        ("complete", "historical", "adapter-architecture"),
    "docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/REVIEW_architecture.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/REVIEW_ecosystem.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/REVIEW_implementation.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/REVIEW_implementation_v3.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/REVIEW_plan_coherence.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/REVIEW_serverless.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/TLS_IMPLEMENTATION_SUMMARY.md":
        ("complete", "historical", "mcp-design"),
    "docs/plans/llm-provider-reconfiguration-v2.md":
        ("complete", "historical", "routing-composition"),
    "docs/plans/mcp-connection-stability-plan.md":
        ("complete", "historical", "mcp-design"),
    "docs/plans/native-macos-automation-backend-plan.md":
        ("draft", "implementation", "terminal"),
    "docs/plans/reviews/config-review.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/reviews/ops-review.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/reviews/security-review.md":
        ("complete", "historical", "convergence-control-plane"),
    "docs/plans/session-buddy-llama-server-ollama-migration.md":
        ("complete", "historical", "routing-composition"),
}


def add_legacy_comment(text: str) -> str:
    """Append a trailing HTML legacy comment on the first 'Status:' / '**Status**' line.

    Avoids touching the body content beyond that one line.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match `**Status**: ...`, `**Status** ...`, `**Status:** ...`, etc.
        if stripped.startswith("**Status") and "Status" in stripped:
            # Extract the original status string for the comment.
            original = stripped.rstrip("\n")
            if "-- see YAML frontmatter" not in original:
                lines[i] = original + "  <!-- legacy status — see YAML frontmatter -->\n"
            break
    return "".join(lines)


def main() -> None:
    repo_root = Path("/Users/les/Projects/mahavishnu")
    results = []
    for rel_path, (status, role, topic) in ASSIGNMENTS.items():
        path = repo_root / rel_path
        if not path.is_file():
            print(f"SKIP (missing): {rel_path}")
            continue
        original = path.read_text(encoding="utf-8")
        if original.lstrip().startswith("---\n"):
            print(f"SKIP (already has frontmatter): {rel_path}")
            continue
        frontmatter = PLAN_FM_TEMPLATE.format(
            status=status, role=role, topic=topic
        )
        body_with_comment = add_legacy_comment(original)
        new_content = frontmatter + body_with_comment
        path.write_text(new_content, encoding="utf-8")
        results.append((rel_path, status, role, topic))
    print(f"\nEdited {len(results)} files:")
    for rel, st, rl, tp in results:
        print(f"  {rel}: status={st} role={rl} topic={tp}")


if __name__ == "__main__":
    main()
