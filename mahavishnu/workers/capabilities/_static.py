"""Static prerequisite checks."""
from __future__ import annotations
import shutil
from dataclasses import dataclass
from typing import Any
from ..registry import WorkerConfig
from ._states import WorkerCapabilityReport, WorkerCapabilityState, WorkerCheck
@dataclass
class StaticContext: settings: Any; env: dict[str,str]
def _resolve(settings: Any,key: str)->Any:
    value=settings
    for part in key.split('.'):
        value=getattr(value,part,None)
        if value is None: return None
    return value
def evaluate_static(worker_type: str, *, config: WorkerConfig, ctx: StaticContext)->WorkerCapabilityReport:
    missing=[]; checks=[]
    if not bool(_resolve(ctx.settings,'workers.enabled')):
        return WorkerCapabilityReport(worker_type,WorkerCapabilityState.CONFIGURED,missing_requirements=['workers.enabled'],safe_reason='workers disabled by config')
    if config.requires_tool and shutil.which(config.requires_tool) is None:
        missing.append(f'tool:{config.requires_tool}'); checks.append(WorkerCheck('binary','fail',config.requires_tool))
    elif config.requires_tool: checks.append(WorkerCheck('binary','pass',config.requires_tool))
    env_missing=[n for n in config.required_env if not ctx.env.get(n)]
    if env_missing: missing.extend(env_missing); checks.append(WorkerCheck('env','fail',','.join(env_missing)))
    elif config.required_env: checks.append(WorkerCheck('env','pass',','.join(config.required_env)))
    for key in config.required_settings:
        if not _resolve(ctx.settings,key): missing.append(f'setting:{key}'); checks.append(WorkerCheck('setting','fail',key))
    state=WorkerCapabilityState.READY if not missing else WorkerCapabilityState.CONFIGURED
    reason='static prerequisites satisfied' if not missing else ','.join(missing)
    return WorkerCapabilityReport(worker_type,state,checks,missing,safe_reason=reason)
