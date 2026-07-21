"""Capability transition observability."""
from __future__ import annotations
from prometheus_client import Counter, Histogram
from oneiric.core.logging import get_logger
from ._safe import safe_error_for_user
from ._states import WorkerCapabilityReport, WorkerCapabilityState
logger=get_logger(__name__)
_TRANSITIONS=Counter('mahavishnu_worker_capability_transitions_total','Worker capability state transitions',('worker_type','from_state','to_state'))
_PROBE_DURATION=Histogram('mahavishnu_worker_capability_probe_duration_seconds','Worker capability probe duration',('worker_type','check_kind','result'))
_CACHE_TOTAL=Counter('mahavishnu_worker_capability_cache_total','Worker capability cache hits and misses',('worker_type','result'))
_last_state={}
def emit_transition(report):
    previous=_last_state.get(report.worker_type)
    if previous is report.state:return
    _TRANSITIONS.labels(report.worker_type,str(previous),str(report.state)).inc(); _last_state[report.worker_type]=report.state
    logger.info('worker_capability_transition',extra={'worker_type':report.worker_type,'from_state':str(previous),'to_state':str(report.state)}); _publish_event(report)
def record_probe(worker_type,kind,duration,result): _PROBE_DURATION.labels(worker_type,kind,result).observe(duration)
def record_probe_failure(report,kind,reason): logger.warning('worker_capability_probe_failed',extra={'worker_type':report.worker_type,'check_kind':kind,'safe_reason':safe_error_for_user(reason)})
def record_cache(worker_type,result): _CACHE_TOTAL.labels(worker_type,result).inc()
def _publish_event(report):
    try: from ...websocket.server import broadcast_event
    except ImportError:return
    payload={'worker_type':report.worker_type,'state':report.state.value,'safe_reason':safe_error_for_user(report.safe_reason),'probe_at':report.probe_at.isoformat()}
    broadcast_event('worker.availability_changed',payload,room='adapters'); broadcast_event('adapter.health_changed',payload,room='adapters')
def reset_for_tests(): _last_state.clear()
