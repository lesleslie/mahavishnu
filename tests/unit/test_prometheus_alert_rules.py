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
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RULES_FILE = _REPO_ROOT / "config" / "prometheus" / "health_aggregator_alerts.yml"
_RULE_TESTS = _REPO_ROOT / "config" / "prometheus" / "tests" / "heartbeat_rules.test.yml"

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
