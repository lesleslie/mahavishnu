"""Async live probes for worker capability evaluation."""
from __future__ import annotations
import asyncio, os, shutil, socket
from collections.abc import Awaitable, Callable
import httpx
from ._safe import safe_error_for_user
from ._states import WorkerCheck
async def _probe_openclaw_gateway(endpoint: str, token: str|None)->WorkerCheck:
    try:
        async with httpx.AsyncClient(timeout=5) as client: r=await client.get(f'{endpoint.rstrip("/")}/health',headers={'Authorization':f'Bearer {token}'} if token else {}); r.raise_for_status(); p=r.json()
    except (httpx.HTTPError,ValueError,OSError) as exc: return WorkerCheck('openclaw_gateway','fail',type(exc).__name__)
    return WorkerCheck('openclaw_gateway','pass' if isinstance(p,dict) and p.get('healthy') else 'fail','ok' if isinstance(p,dict) and p.get('healthy') else 'unhealthy')
async def _probe_openclaw_cli(binary: str)->WorkerCheck:
    if shutil.which(binary) is None:return WorkerCheck('openclaw_cli','fail',f'missing:{binary}')
    try:
        p=await asyncio.create_subprocess_exec(binary,'--version',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE); out,_=await asyncio.wait_for(p.communicate(),5)
    except (asyncio.TimeoutError,OSError) as exc:return WorkerCheck('openclaw_cli','fail',type(exc).__name__)
    return WorkerCheck('openclaw_cli','pass' if p.returncode==0 else 'fail',safe_error_for_user(out.decode().strip() or 'ok') if p.returncode==0 else 'non_zero_exit')
async def _probe_container_daemon(runtime: str)->WorkerCheck:
    if shutil.which(runtime) is None:return WorkerCheck('container_daemon','fail',f'missing:{runtime}')
    try:
        p=await asyncio.create_subprocess_exec(runtime,'version','--format','{{.Server.Version}}',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE); out,_=await asyncio.wait_for(p.communicate(),5)
    except (asyncio.TimeoutError,OSError) as exc:return WorkerCheck('container_daemon','fail',type(exc).__name__)
    return WorkerCheck('container_daemon','pass' if p.returncode==0 else 'fail',safe_error_for_user(out.decode().strip() or 'ok') if p.returncode==0 else 'daemon_unreachable')
async def _probe_auth_presence(names: list[str])->WorkerCheck:
    missing=[n for n in names if not os.environ.get(n)]; return WorkerCheck('auth','fail' if missing else 'pass',','.join(missing) if missing else 'ok')
async def _probe_provider_request(provider: str,env_var: str,endpoint: str)->WorkerCheck:
    token=os.environ.get(env_var)
    if not token:return WorkerCheck(f'{provider}_auth','fail','missing')
    try:
        async with httpx.AsyncClient(timeout=5) as client:r=await client.get(endpoint,headers={'Authorization':f'Bearer {token}'}); r.raise_for_status()
    except httpx.HTTPError as exc:return WorkerCheck(f'{provider}_auth','fail',safe_error_for_user(type(exc).__name__))
    return WorkerCheck(f'{provider}_auth','pass','ok')
PROBES={'openclaw_gateway':_probe_openclaw_gateway,'openclaw_cli':_probe_openclaw_cli,'container_daemon':_probe_container_daemon,'auth_presence':_probe_auth_presence,'provider_request':_probe_provider_request}
PROVIDER_PROBES={'minimax':('MINIMAX_API_KEY','https://api.minimax.io/v1/models'),'anthropic':('ANTHROPIC_API_KEY','https://api.anthropic.com/v1/models'),'openai':('OPENAI_API_KEY','https://api.openai.com/v1/models'),'qwen':('QWEN_API_KEY','https://dashscope.aliyuncs.com/api/v1/models')}
