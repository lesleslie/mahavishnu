"""Shared dashboard configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


@dataclass
class DashboardPanel:
    """A dashboard panel."""

    title: str
    query: str
    panel_type: str = "graph"
    width: int = 12
    height: int = 6
    datasource: str = "Prometheus"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "query": self.query,
            "type": self.panel_type,
            "width": self.width,
            "height": self.height,
            "datasource": self.datasource,
        }


@dataclass
class DashboardConfig:
    """Dashboard configuration."""

    title: str
    panels: list[DashboardPanel] = field(default_factory=list)
    refresh_interval: int = 30
    tags: list[str] = field(default_factory=list)

    def add_panel(self, panel: DashboardPanel) -> None:
        self.panels.append(panel)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "panels": [p.to_dict() for p in self.panels],
            "refresh_interval": self.refresh_interval,
            "tags": self.tags,
        }

    def to_grafana_json(self) -> str:
        grafana = {
            "dashboard": {
                "title": self.title,
                "uid": self.title.lower().replace(" ", "-"),
                "panels": [
                    {
                        "id": i + 1,
                        "title": p.title,
                        "type": p.panel_type,
                        "gridPos": {
                            "x": 0,
                            "y": i * p.height,
                            "w": p.width,
                            "h": p.height,
                        },
                        "targets": [{"expr": p.query, "datasource": p.datasource}],
                    }
                    for i, p in enumerate(self.panels)
                ],
                "refresh": f"{self.refresh_interval}s",
                "tags": self.tags,
            },
            "overwrite": True,
        }
        return json.dumps(grafana, indent=2)
