"""Integration smoke tests for HatchetAdapter.

Skipped automatically unless HATCHET_CLIENT_TOKEN is set.
Run manually:
    HATCHET_CLIENT_TOKEN=<token> pytest tests/integration/test_hatchet_smoke.py -v -s
"""

from __future__ import annotations

import os

import pytest

SKIP_REASON = "HATCHET_CLIENT_TOKEN not set — skipping live Hatchet test"


@pytest.mark.skipif(not os.environ.get("HATCHET_CLIENT_TOKEN"), reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_hatchet_adapter_initialize_live():
    from mahavishnu.core.config import HatchetConfig
    from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl

    cfg = HatchetConfig()
    adapter = HatchetAdapterImpl(config=cfg)
    await adapter.initialize()
    health = await adapter.get_health()
    assert health["status"] in ("healthy", "degraded")
    await adapter.cleanup()


@pytest.mark.skipif(not os.environ.get("HATCHET_CLIENT_TOKEN"), reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_hatchet_adapter_type_and_capabilities():
    from mahavishnu.core.adapters.base import AdapterType
    from mahavishnu.core.config import HatchetConfig
    from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl

    adapter = HatchetAdapterImpl(config=HatchetConfig())
    assert adapter.adapter_type == AdapterType.HATCHET
    assert adapter.capabilities.supports_multi_agent is True
    assert adapter.capabilities.can_deploy_flows is True
