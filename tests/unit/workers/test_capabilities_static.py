from __future__ import annotations

from dataclasses import dataclass, field

from mahavishnu.workers.capabilities import WorkerCapabilityState, evaluate_worker_capabilities


@dataclass
class C: runtime:str|None=None; socket_path:str|None=None
@dataclass
class W: enabled:bool=True; container:C=field(default_factory=C)
@dataclass
class S: workers:W=field(default_factory=W)
def test_disabled():
 r=evaluate_worker_capabilities('terminal-claude',settings=S(W(False))); assert r.state is WorkerCapabilityState.CONFIGURED
def test_missing(monkeypatch):
 monkeypatch.setattr('shutil.which',lambda _:None); r=evaluate_worker_capabilities('terminal-claude',settings=S()); assert r.state is WorkerCapabilityState.CONFIGURED
def test_ready(monkeypatch):
 monkeypatch.setattr('shutil.which',lambda n:f'/usr/bin/{n}'); r=evaluate_worker_capabilities('terminal-claude',settings=S()); assert r.state is WorkerCapabilityState.READY
