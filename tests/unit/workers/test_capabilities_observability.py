from __future__ import annotations
from dataclasses import dataclass,field
import pytest
from mahavishnu.workers.capabilities import evaluate_worker_capabilities,reset_for_tests
@dataclass
class C: runtime:str|None=None; socket_path:str|None=None
@dataclass
class W: enabled:bool=True; container:C=field(default_factory=C)
@dataclass
class S: workers:W=field(default_factory=W)
def test_log(monkeypatch,caplog):
 reset_for_tests(); monkeypatch.setattr('shutil.which',lambda _:None)
 with caplog.at_level('INFO'): evaluate_worker_capabilities('terminal-claude',settings=S())
 assert any('worker_capability_transition' in r.message for r in caplog.records)
def test_event(monkeypatch):
 reset_for_tests(); calls=[]
 import mahavishnu.workers.capabilities._observability as o
 monkeypatch.setattr(o,'_publish_event',lambda r:calls.append(r)); monkeypatch.setattr('shutil.which',lambda _:None); evaluate_worker_capabilities('terminal-claude',settings=S()); assert calls
def test_probe_warning(monkeypatch,caplog):
 reset_for_tests(); monkeypatch.setattr('shutil.which',lambda _:None)
 with caplog.at_level('WARNING'): evaluate_worker_capabilities('terminal-claude',settings=S(),force_live=True)
 assert any('worker_capability_probe_failed' in r.message for r in caplog.records)
