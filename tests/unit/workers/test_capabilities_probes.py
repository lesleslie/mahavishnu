from __future__ import annotations
from dataclasses import dataclass,field
import pytest
from mahavishnu.workers.capabilities import WorkerCapabilityState,evaluate_worker_capabilities
@dataclass
class C: runtime:str|None=None; socket_path:str|None=None
@dataclass
class W: enabled:bool=True; container:C=field(default_factory=C)
@dataclass
class S: workers:W=field(default_factory=W)
def test_unreachable(monkeypatch):
 monkeypatch.setenv('OPENCLAW_GATEWAY_URL','http://127.0.0.1:1'); r=evaluate_worker_capabilities('gateway-openclaw',settings=S(),force_live=True); assert r.state is WorkerCapabilityState.READY
def test_healthy(monkeypatch):
 monkeypatch.setenv('OPENCLAW_GATEWAY_URL','http://gateway.test')
 class R:
  def raise_for_status(self): pass
  def json(self): return {'healthy':True}
 class A:
  def __init__(self,*a,**k): pass
  async def __aenter__(self): return self
  async def __aexit__(self,*a): pass
  async def get(self,*a,**k): return R()
 monkeypatch.setattr('httpx.AsyncClient',A); r=evaluate_worker_capabilities('gateway-openclaw',settings=S(),force_live=True); assert r.state is WorkerCapabilityState.AVAILABLE
