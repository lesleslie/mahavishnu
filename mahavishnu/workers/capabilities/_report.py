"""Public entry points for capability evaluation."""
from __future__ import annotations
import asyncio, os, time
from collections.abc import Iterable
from typing import Any
from ..registry import WORKER_REGISTRY, get_worker_config
from ._cache import get as cache_get, put as cache_put, invalidate as cache_invalidate
from ._observability import emit_transition, record_cache, record_probe, record_probe_failure
from ._probes import PROBES
from ._states import WorkerCapabilityReport, WorkerCapabilityState
from ._static import StaticContext, evaluate_static
def _run_live(report,config,settings):
    if report.state is not WorkerCapabilityState.READY:return report
    if config.worker_type=='gateway-openclaw': fn=PROBES['openclaw_gateway']; args=(os.getenv('OPENCLAW_GATEWAY_URL',''),os.getenv('OPENCLAW_GATEWAY_TOKEN'))
    elif config.worker_type=='terminal-openclaw': fn=PROBES['openclaw_cli']; args=('openclaw',)
    elif config.requires_tool:
        fn=PROBES['openclaw_cli']; args=(config.requires_tool,)
    else:return report
    start=time.perf_counter(); check=asyncio.run(fn(*args)); record_probe(config.worker_type,check.kind,time.perf_counter()-start,check.status)
    if check.status=='fail':record_probe_failure(report,check.kind,check.safe_reason or 'unknown')
    return WorkerCapabilityReport(report.worker_type,WorkerCapabilityState.AVAILABLE if check.status=='pass' else WorkerCapabilityState.READY,report.checks+[check],report.missing_requirements,safe_reason=report.safe_reason)
def evaluate_worker_capabilities(worker_type: str, *, settings: Any, force_live: bool=False)->WorkerCapabilityReport:
    key=f'{worker_type}:full' if force_live else f'{worker_type}:static'; cached=None
    if cached is not None:record_cache(worker_type,'hit'); return cached
    record_cache(worker_type,'miss'); config=get_worker_config(worker_type)
    if config is None: report=WorkerCapabilityReport(worker_type,WorkerCapabilityState.REGISTERED,missing_requirements=[f'unknown:{worker_type}'],safe_reason='unknown worker type')
    else: report=evaluate_static(worker_type,config=config,ctx=StaticContext(settings,{k:v for k,v in os.environ.items()})); report=_run_live(report,config,settings) if force_live else report
    cache_put(key,report); emit_transition(report); return report
def evaluate_all_capabilities(*,settings: Any,force_live: bool=False)->dict[str,WorkerCapabilityReport]: return {w:evaluate_worker_capabilities(w,settings=settings,force_live=force_live) for w in WORKER_REGISTRY}
def select_routable_workers(candidates: Iterable[str]|None=None,*,settings: Any,require_available: bool=False)->list[str]:
    result=[]
    for w in list(candidates) if candidates is not None else list(WORKER_REGISTRY):
        state=evaluate_worker_capabilities(w,settings=settings).state
        if state is WorkerCapabilityState.AVAILABLE or (state is WorkerCapabilityState.READY and not require_available):result.append(w)
    return result
def invalidate_capability(worker_type: str)->None: cache_invalidate(worker_type)
