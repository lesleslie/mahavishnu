"""Tests for dashboard configuration models.

Tests cover:
- DashboardPanel creation, defaults, to_dict
- DashboardConfig creation, add_panel, to_dict, to_grafana_json
- Grafana JSON structure validation
"""

import json

from mahavishnu.core.monitoring import DashboardConfig, DashboardPanel


class TestDashboardPanel:
    """Test DashboardPanel dataclass."""

    def test_defaults(self):
        panel = DashboardPanel(title="Test Panel", query="up")
        assert panel.title == "Test Panel"
        assert panel.query == "up"
        assert panel.panel_type == "graph"
        assert panel.width == 12
        assert panel.height == 6
        assert panel.datasource == "Prometheus"

    def test_custom_values(self):
        panel = DashboardPanel(
            title="CPU Usage",
            query="rate(cpu_seconds_total[5m])",
            panel_type="stat",
            width=6,
            height=4,
            datasource="InfluxDB",
        )
        assert panel.panel_type == "stat"
        assert panel.width == 6
        assert panel.height == 4
        assert panel.datasource == "InfluxDB"

    def test_to_dict(self):
        panel = DashboardPanel(
            title="Memory",
            query="memory_usage",
            panel_type="gauge",
        )
        d = panel.to_dict()
        assert d == {
            "title": "Memory",
            "query": "memory_usage",
            "type": "gauge",  # Note: "type" not "panel_type"
            "width": 12,
            "height": 6,
            "datasource": "Prometheus",
        }

    def test_to_dict_maps_panel_type_to_type(self):
        """to_dict should map panel_type to 'type' key."""
        panel = DashboardPanel(title="T", query="q", panel_type="table")
        d = panel.to_dict()
        assert "type" in d
        assert d["type"] == "table"
        assert "panel_type" not in d


class TestDashboardConfig:
    """Test DashboardConfig dataclass."""

    def test_defaults(self):
        config = DashboardConfig(title="Test Dashboard")
        assert config.title == "Test Dashboard"
        assert config.panels == []
        assert config.refresh_interval == 30
        assert config.tags == []

    def test_add_panel(self):
        config = DashboardConfig(title="Test")
        panel = DashboardPanel(title="CPU", query="cpu")
        config.add_panel(panel)
        assert len(config.panels) == 1
        assert config.panels[0].title == "CPU"

    def test_add_multiple_panels(self):
        config = DashboardConfig(title="Test")
        config.add_panel(DashboardPanel(title="P1", query="q1"))
        config.add_panel(DashboardPanel(title="P2", query="q2"))
        config.add_panel(DashboardPanel(title="P3", query="q3"))
        assert len(config.panels) == 3

    def test_to_dict_empty(self):
        config = DashboardConfig(title="Empty Dashboard")
        d = config.to_dict()
        assert d["title"] == "Empty Dashboard"
        assert d["panels"] == []
        assert d["refresh_interval"] == 30
        assert d["tags"] == []

    def test_to_dict_with_panels(self):
        config = DashboardConfig(title="Test", tags=["monitoring"])
        config.add_panel(DashboardPanel(title="CPU", query="cpu_usage"))
        d = config.to_dict()
        assert len(d["panels"]) == 1
        assert d["panels"][0]["title"] == "CPU"
        assert d["tags"] == ["monitoring"]

    def test_to_dict_with_custom_refresh(self):
        config = DashboardConfig(title="Test", refresh_interval=60)
        d = config.to_dict()
        assert d["refresh_interval"] == 60


class TestDashboardConfigGrafanaJson:
    """Test to_grafana_json output."""

    def _parse_grafana(self, config):
        return json.loads(config.to_grafana_json())

    def test_basic_structure(self):
        config = DashboardConfig(title="My Dashboard")
        grafana = self._parse_grafana(config)
        assert grafana["overwrite"] is True
        assert "dashboard" in grafana

    def test_uid_from_title(self):
        config = DashboardConfig(title="My Dashboard")
        grafana = self._parse_grafana(config)
        assert grafana["dashboard"]["uid"] == "my-dashboard"

    def test_uid_lowercases_and_replaces_spaces(self):
        config = DashboardConfig(title="Production Monitoring")
        grafana = self._parse_grafana(config)
        assert grafana["dashboard"]["uid"] == "production-monitoring"

    def test_panels_with_ids(self):
        config = DashboardConfig(title="Test")
        config.add_panel(DashboardPanel(title="P1", query="q1"))
        config.add_panel(DashboardPanel(title="P2", query="q2"))
        grafana = self._parse_grafana(config)
        panels = grafana["dashboard"]["panels"]
        assert len(panels) == 2
        assert panels[0]["id"] == 1
        assert panels[1]["id"] == 2

    def test_panel_grid_positioning(self):
        config = DashboardConfig(title="Test")
        config.add_panel(DashboardPanel(title="P1", query="q1", width=6, height=4))
        grafana = self._parse_grafana(config)
        panel = grafana["dashboard"]["panels"][0]
        assert panel["gridPos"]["x"] == 0
        assert panel["gridPos"]["y"] == 0
        assert panel["gridPos"]["w"] == 6
        assert panel["gridPos"]["h"] == 4

    def test_panel_grid_stacking(self):
        """Panels should stack vertically."""
        config = DashboardConfig(title="Test")
        config.add_panel(DashboardPanel(title="P1", query="q1", height=4))
        config.add_panel(DashboardPanel(title="P2", query="q2", height=6))
        grafana = self._parse_grafana(config)
        panels = grafana["dashboard"]["panels"]
        # Panel 2 should start at y = 4 (height of panel 1)
        assert panels[0]["gridPos"]["y"] == 0
        assert panels[1]["gridPos"]["y"] == 4

    def test_panel_targets(self):
        config = DashboardConfig(title="Test")
        config.add_panel(
            DashboardPanel(
                title="CPU",
                query="rate(cpu[5m])",
                datasource="Prometheus",
            )
        )
        grafana = self._parse_grafana(config)
        targets = grafana["dashboard"]["panels"][0]["targets"]
        assert len(targets) == 1
        assert targets[0]["expr"] == "rate(cpu[5m])"
        assert targets[0]["datasource"] == "Prometheus"

    def test_refresh_interval(self):
        config = DashboardConfig(title="Test", refresh_interval=60)
        grafana = self._parse_grafana(config)
        assert grafana["dashboard"]["refresh"] == "60s"

    def test_tags(self):
        config = DashboardConfig(title="Test", tags=["monitoring", "production"])
        grafana = self._parse_grafana(config)
        assert grafana["dashboard"]["tags"] == ["monitoring", "production"]

    def test_empty_panels_produces_valid_json(self):
        config = DashboardConfig(title="Empty")
        grafana = self._parse_grafana(config)
        assert grafana["dashboard"]["panels"] == []

    def test_json_is_valid(self):
        """Output should be valid JSON."""
        config = DashboardConfig(
            title="Complex Dashboard",
            tags=["test"],
            refresh_interval=15,
        )
        config.add_panel(DashboardPanel(title="P1", query="q1", panel_type="stat"))
        config.add_panel(DashboardPanel(title="P2", query="q2", panel_type="table"))
        json_str = config.to_grafana_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
