"""The Prometheus alert rules must parse, and the heartbeat rules must behave.

``config/prometheus/health_aggregator_alerts.yml`` is loaded by Prometheus
from ``rule_files``, but nothing in the test suite reads it — so a rule with
a broken expression, or one that fires on the wrong series, would sit in
the file until an operator noticed it missing at 3am.

``promtool`` is the tool for this: ``check rules`` parses a rule file and
``test rules`` runs a rule against synthetic input series and asserts what
fires. The heartbeat rules have a unit test at
``config/prometheus/tests/heartbeat_rules.test.yml``.

The label trap deserves its own guard, because it is invisible in a
review and fatal in production. The scrape config labels the TARGET with
``service: akosha`` — akosha's receiver is what exposed the counter — and
Prometheus renames the counter's own ``service`` label to
``exported_service``. Every series therefore carries::

    service="akosha"                  <- the target that exposed it
    exported_service="session-buddy"  <- the producer that emitted it

An alert that read ``{{ $labels.service }}`` would announce "akosha" for
every producer in the fleet: firing correctly and pointing at the wrong
service, which is worse than not firing at all because it looks like it
works.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RULES_FILE = _REPO_ROOT / "config" / "prometheus" / "health_aggregator_alerts.yml"
_RULE_TESTS = _REPO_ROOT / "config" / "prometheus" / "tests" / "heartbeat_rules.test.yml"
_RUNBOOK = _REPO_ROOT / "docs" / "runbooks" / "OTEL_HEARTBEAT.md"

_PROMTOOL = shutil.which("promtool")
_requires_promtool = pytest.mark.skipif(_PROMTOOL is None, reason="promtool is not installed")


def _promtool(*args: str) -> subprocess.CompletedProcess[str]:
    assert _PROMTOOL is not None  # guarded by _requires_promtool
    return subprocess.run(
        [_PROMTOOL, *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@_requires_promtool
def test_the_alert_rules_parse() -> None:
    """A rule with a broken expression never loads, and never says so."""
    result = _promtool("check", "rules", str(_RULES_FILE))
    assert result.returncode == 0, result.stdout + result.stderr


@_requires_promtool
def test_the_heartbeat_rules_behave() -> None:
    """The heartbeat rules fire on the right series, and clear when they should.

    The unit test asserts the full label set of the resulting alert, so a
    rule that fires on the scrape target rather than on the producer fails
    here rather than at 3am.
    """
    result = _promtool("test", "rules", str(_RULE_TESTS))
    assert result.returncode == 0, result.stdout + result.stderr


class TestTheLabelTrap:
    """The producer is ``exported_service``, never ``service``."""

    def _heartbeat_group(self) -> str:
        text = _RULES_FILE.read_text(encoding="utf-8")
        start = text.index("  - name: bodai-otel-heartbeat")
        return text[start:]

    def test_the_annotations_name_the_producer(self) -> None:
        group = self._heartbeat_group()
        assert "{{ $labels.exported_service }}" in group, (
            "the heartbeat annotations must name the producer via "
            "exported_service — `service` is the scrape target's label and "
            "is 'akosha' for every producer"
        )
        assert "{{ $labels.service }}" not in group, (
            "`{{ $labels.service }}` resolves to the scrape target's name "
            "('akosha'), not the producer that went quiet"
        )

    def test_the_trap_is_documented_where_someone_would_hit_it(self) -> None:
        group = self._heartbeat_group()
        assert "exported_service" in group, "the label trap must be explained in the file"

    def test_the_scrape_config_is_the_reason(self) -> None:
        """The guard is only meaningful while the scrape config does this."""
        targets = _REPO_ROOT / "monitoring" / "file_sd" / "verified_metrics_targets.yml"
        text = targets.read_text(encoding="utf-8")
        assert "service: akosha" in text, (
            "the scrape config labels the target with `service: akosha`, "
            "which is why the metric's own label becomes exported_service"
        )


def _github_anchor(heading: str) -> str:
    """Reproduce GitHub's heading-slug algorithm.

    Lowercase, drop everything that is not a word character, a hyphen, or a
    space, then turn spaces into hyphens. GitHub resolves a ``#fragment`` in
    a markdown URL to a heading by exactly this rule, so the test has to
    reproduce it to check an anchor.
    """
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


class TestTheRunbookIsReal:
    """A ``runbook_url`` that 404s is not a runbook.

    The heartbeat alerts are the only thing standing between a silent
    producer and an operator who never learns about it. Their annotations
    point at ``docs/runbooks/OTEL_HEARTBEAT.md``; if that file is renamed,
    moved, or its headings changed, the link rots silently — Prometheus
    does not care whether a URL resolves, and nothing else in the test
    suite reads these annotations.
    """

    def _heartbeat_urls(self) -> list[str]:
        text = _RULES_FILE.read_text(encoding="utf-8")
        start = text.index("  - name: bodai-otel-heartbeat")
        return re.findall(r'runbook_url: "([^"]+)"', text[start:])

    def test_the_runbook_file_is_present(self) -> None:
        assert _RUNBOOK.is_file(), (
            f"{_RUNBOOK} is missing — the heartbeat alerts point at it"
        )

    def test_every_heartbeat_alert_points_at_the_runbook(self) -> None:
        urls = self._heartbeat_urls()
        assert len(urls) == 3, f"expected one runbook_url per heartbeat rule, found {len(urls)}"
        for url in urls:
            assert "docs/runbooks/OTEL_HEARTBEAT.md" in url, (
                f"the heartbeat rules must point at the runbook, not at a spec: {url}"
            )

    def test_every_anchor_resolves_to_a_real_heading(self) -> None:
        """The fragment after the ``#`` must be a heading in the runbook."""
        assert _RUNBOOK.is_file()
        headings = [
            _github_anchor(match.group(1))
            for match in re.finditer(r"^#{1,6}\s+(.*)$", _RUNBOOK.read_text(encoding="utf-8"), re.M)
        ]
        for url in self._heartbeat_urls():
            fragment = url.rsplit("#", 1)[-1]
            assert fragment in headings, (
                f"the runbook has no heading that resolves to #{fragment}; "
                f"the alert's link would land on a page with no such section. "
                f"Headings present: {sorted(set(headings))}"
            )

    def test_the_runbook_names_the_label_trap(self) -> None:
        """The two traps that make this runbook necessary."""
        text = _RUNBOOK.read_text(encoding="utf-8")
        assert "exported_service" in text, (
            "the runbook must document the exported_service/service label trap"
        )
        assert "increase(" in text, (
            "the runbook must warn that the raw counters are cumulative and "
            "only `increase()` over a recent window says anything about now"
        )
