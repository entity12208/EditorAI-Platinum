#!/usr/bin/env python3
"""
Distributed Ollama Coordinator Server
Manages worker nodes and routes inference requests using queue-based architecture
"""

import asyncio
import json
import os
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from aiohttp import web
import aiohttp
import uuid


# ── Inline config (optional alternative to environment variables) ────────────
# Fill values in here to configure the coordinator without exporting env vars.
# Uses os.environ.setdefault, so a REAL env var still takes precedence and
# every downstream read (all of which go through os.environ) works unchanged.
#
# SECURITY: HF_TOKEN is a WRITE-access secret. This file is gitignored, so it
# can't be committed by accident — but if you ever un-ignore cloud/ or copy
# this file into a public repo with the token filled in, HuggingFace will
# auto-revoke the leaked token and the dataset is writable by anyone until
# then. Keep the filled-in copy on the server box only.
INLINE_CONFIG = {
    'HF_DATASET_REPO':    '',       # e.g. 'EditorAI-Geode/editorai-telemetry'
    'HF_TOKEN':           '',       # 'hf_...' token with WRITE access (SERVER-ONLY, never commit)
    'HF_DATASET_PRIVATE': 'true',   # 'false' = public dataset (raw user prompts!)
    'HF_SYNC_MINUTES':    '10',     # commit interval in minutes
    'PLATINUM_DATA_DIR': '.',     # where train.jsonl / contributions/ live
    # 'PLATINUM_LOG': '',           # path for a persistent coordinator log
    # 'PLATINUM_CHAINS': '',        # JSON file of extra/overriding fallback chains
}
for _key, _val in INLINE_CONFIG.items():
    if _val:
        os.environ.setdefault(_key, _val)


@web.middleware
async def cors_middleware(request, handler):
    """Add CORS headers to every response so browsers can read the API."""
    if request.method == 'OPTIONS':
        return web.Response(headers={
            'Access-Control-Allow-Origin':  '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        })
    response = await handler(request)
    # A long-poll StreamResponse (blocking /api/generate) has already sent its
    # headers by the time it returns here — sets its own CORS, skip it.
    if not getattr(response, 'prepared', False):
        response.headers['Access-Control-Allow-Origin']  = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-7s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')
# Optional persistent log: set PLATINUM_LOG=/path/to/coordinator.log
if os.environ.get('PLATINUM_LOG'):
    from logging.handlers import RotatingFileHandler
    _fh = RotatingFileHandler(os.environ['PLATINUM_LOG'],
                              maxBytes=10_000_000, backupCount=3)
    _fh.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-7s %(message)s', '%Y-%m-%d %H:%M:%S'))
    logging.getLogger().addHandler(_fh)
logger = logging.getLogger(__name__)


class WorkerStatus(Enum):
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class RequestStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class WorkerResources:
    """Resources available on a worker node"""
    total_ram_gb: float
    available_ram_gb: float
    total_vram_gb: float
    available_vram_gb: float
    total_disk_gb: float
    available_disk_gb: float
    cpu_count: int
    gpu_name: Optional[str] = None


@dataclass
class Worker:
    """Worker node information"""
    id: str
    address: str
    port: int
    status: WorkerStatus
    resources: WorkerResources
    models: List[str]
    last_heartbeat: datetime
    current_requests: int = 0
    total_requests: int = 0
    
    def to_dict(self):
        data = asdict(self)
        data['status'] = self.status.value
        data['last_heartbeat'] = self.last_heartbeat.isoformat()
        return data


@dataclass
class QueuedRequest:
    """Queued generation request"""
    request_id: str
    model: str
    prompt: str
    options: dict
    status: RequestStatus
    created_at: datetime
    assigned_worker: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    completed_at: Optional[datetime] = None
    original_model: str = ''
    fallback_chain: Optional[list] = None
    chain_index: int = 0
    chain_attempts: int = 0
    # asyncio.Event set exactly once, when status reaches a final state
    # (COMPLETED / FAILED / TIMEOUT). The blocking /api/generate long-poll
    # waits on it instead of busy-polling the status.
    waiter: Optional[object] = None


# Fallback chains: (model, max_tries_before_moving_on) pairs.
# "best" resolves to the full chain: glm-4.7-flash x2, glm-4.5-flash x1,
# glm-4.7-flash x1, then local entity12208/editorai:v2 as last resort.
FALLBACK_CHAINS = {
    'best': [
        ('glm-4.7-flash', 2),
        ('glm-4.5-flash', 1),
        ('glm-4.7-flash', 1),
        ('entity12208/editorai:v2', 1),
    ],
    'glm-4.7-flash': [
        ('glm-4.7-flash', 2),
        ('glm-4.5-flash', 1),
        ('glm-4.7-flash', 1),
        ('entity12208/editorai:v2', 1),
    ],
    'JTA-GLM-EDITORAI': [
        ('JTA-GLM-EDITORAI', 2),
        ('glm-4.5-flash', 1),
        ('JTA-GLM-EDITORAI', 1),
        ('entity12208/editorai:v2', 1),
    ],
    # Advertised by JTA donor workers as a literal model name; without this
    # entry it resolved to a single-attempt chain with no fallback.
    'best-available-jta': [
        ('best-available-jta', 1),
        ('JTA-GLM-EDITORAI', 2),
        ('glm-4.5-flash', 1),
        ('glm-4.7-flash', 1),
        ('entity12208/editorai:v2', 1),
    ],
    'glm-4.5-flash': [
        ('glm-4.5-flash', 2),
        ('entity12208/editorai:v2', 1),
    ],
    'entity12208/editorai:v2': [
        ('entity12208/editorai:v2', 1),
    ],
}


def _normalise_chain(raw) -> Optional[list]:
    """Accept ["a", "b"] or [["a", 2], ["b", 1]] or [{"model": "a",
    "tries": 2}] and return the internal [(model, tries)] form."""
    if not isinstance(raw, list) or not raw:
        return None
    chain = []
    for hop in raw:
        if isinstance(hop, str):
            chain.append((hop, 1))
        elif isinstance(hop, (list, tuple)) and hop:
            model = str(hop[0])
            tries = int(hop[1]) if len(hop) > 1 else 1
            chain.append((model, max(1, tries)))
        elif isinstance(hop, dict) and hop.get('model'):
            chain.append((str(hop['model']),
                          max(1, int(hop.get('tries', 1)))))
        else:
            return None
    return chain or None


def load_chain_overrides(path: str) -> Dict[str, list]:
    """Read operator-defined fallback chains from a JSON file.

    Optional (PLATINUM_CHAINS). Now that workers can advertise arbitrary tags
    from arbitrary providers, an operator needs a way to define chains for
    their own tags without editing this file. Anything defined here overrides
    the built-in FALLBACK_CHAINS entry of the same name; everything else is
    untouched, so the default behaviour is bit-for-bit unchanged when the
    file is absent.

    Example:
      {
        "best":     [["mygw/llama-3.1-70b", 2], ["deepseek-chat", 1]],
        "cheapest": ["deepseek-chat", "fake-gpt-small"]
      }
    """
    if not path:
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.info(f"PLATINUM_CHAINS={path} not found yet; using built-in chains")
        return {}
    except (OSError, ValueError) as e:
        logger.error(f"Could not read chain overrides {path}: {e}")
        return {}
    if not isinstance(data, dict):
        logger.error(f"{path}: expected a JSON object of tag -> chain")
        return {}
    out: Dict[str, list] = {}
    for tag, raw in data.items():
        chain = _normalise_chain(raw)
        if chain is None:
            logger.warning(f"{path}: ignoring bad chain for {tag!r}")
            continue
        out[str(tag)] = chain
    if out:
        logger.info(f"Loaded {len(out)} fallback chain override(s) from {path}")
    return out


class CoordinatorServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self._contrib_times = {}  # ip-hash -> [timestamps] for /api/contribute
        self._train_hashes = self._load_train_hashes()  # dedupe for train.jsonl
        self._hf_scheduler = None  # huggingface_hub CommitScheduler (opt-in)
        self.host = host
        self.port = port
        self.workers: Dict[str, Worker] = {}
        self.request_queue: Dict[str, QueuedRequest] = {}
        self.heartbeat_timeout = 30
        self.request_timeout = 300
        # Fallback chains: built-ins, optionally overridden/extended by a
        # JSON file (PLATINUM_CHAINS) so operators can define chains over
        # whatever tags their providers advertise. Absent file = old behaviour.
        self.fallback_chains: Dict[str, list] = dict(FALLBACK_CHAINS)
        self._chains_path = os.environ.get('PLATINUM_CHAINS', '')
        self._chains_mtime: Optional[float] = None
        self._reload_chains()
        # Restore the worker registry from the last run. Without this, a
        # coordinator restart orphans every connected worker: old clients
        # never re-register (their heartbeats just 404 forever), /api/tags
        # goes empty, and the mod reports "no models available".
        self._load_workers()

    def _reload_chains(self) -> bool:
        """(Re)apply chain overrides; returns True when something changed."""
        if not self._chains_path:
            return False
        try:
            stamp = os.stat(self._chains_path).st_mtime
        except OSError:
            return False
        if stamp == self._chains_mtime:
            return False
        self._chains_mtime = stamp
        overrides = load_chain_overrides(self._chains_path)
        merged = dict(FALLBACK_CHAINS)
        merged.update(overrides)
        changed = merged != self.fallback_chains
        self.fallback_chains = merged
        return changed

    def chain_for(self, model: str) -> list:
        """The fallback chain for a requested tag.

        Unknown tags get a single-hop chain — exactly what happened before —
        so any tag a worker advertises is servable without configuration.

        If a live worker advertises the requested tag LITERALLY but the named
        chain doesn't start with it, the literal tag is prepended. Without
        this, a provider that maps its own tag onto a chain alias (e.g. a
        worker advertising `best`) would 503 even though it can serve the
        request, because every hop of the built-in chain names a different
        model. In production nothing advertises the alias names, so the
        built-in chains behave exactly as before.
        """
        chain = self.fallback_chains.get(model)
        if chain is None:
            return [(model, 1)]
        if chain[0][0] != model and self._model_online(model):
            logger.info(f"Chain for {model!r}: a worker serves it directly, "
                        "trying that first")
            return [(model, 1)] + list(chain)
        return chain
        
    async def register_worker(self, request: web.Request) -> web.Response:
        """Register a new worker node"""
        try:
            data = await request.json()
            
            worker_id = data.get('worker_id', str(uuid.uuid4()))
            address = data.get('address', request.remote)
            port = data.get('port', 11435)
            
            resources = WorkerResources(
                total_ram_gb=data['resources']['total_ram_gb'],
                available_ram_gb=data['resources']['available_ram_gb'],
                total_vram_gb=data['resources']['total_vram_gb'],
                available_vram_gb=data['resources']['available_vram_gb'],
                total_disk_gb=data['resources']['total_disk_gb'],
                available_disk_gb=data['resources']['available_disk_gb'],
                cpu_count=data['resources']['cpu_count'],
                gpu_name=data['resources'].get('gpu_name')
            )
            
            worker = Worker(
                id=worker_id,
                address=address,
                port=port,
                status=WorkerStatus.IDLE,
                resources=resources,
                models=data.get('models', []),
                last_heartbeat=datetime.now()
            )
            
            self.workers[worker_id] = worker
            self._save_workers()

            logger.info(f"Registered worker {worker_id}")
            logger.info(f"  VRAM: {resources.available_vram_gb:.1f}/{resources.total_vram_gb:.1f} GB")
            logger.info(f"  RAM: {resources.available_ram_gb:.1f}/{resources.total_ram_gb:.1f} GB")
            logger.info(f"  Models: {', '.join(worker.models[:5])}{'...' if len(worker.models) > 5 else ''}")
            
            return web.json_response({
                'status': 'success',
                'worker_id': worker_id,
                'message': 'Worker registered successfully'
            })
            
        except Exception as e:
            logger.error(f"Error registering worker: {e}")
            return web.json_response({
                'status': 'error',
                'message': str(e)
            }, status=400)
    
    async def heartbeat(self, request: web.Request) -> web.Response:
        """Receive heartbeat from worker"""
        try:
            data = await request.json()
            worker_id = data.get('worker_id')
            
            if worker_id not in self.workers:
                return web.json_response({
                    'status': 'error',
                    'message': 'Worker not registered'
                }, status=404)
            
            worker = self.workers[worker_id]
            worker.last_heartbeat = datetime.now()
            
            if 'resources' in data:
                res = data['resources']
                worker.resources.available_ram_gb = res.get('available_ram_gb', worker.resources.available_ram_gb)
                worker.resources.available_vram_gb = res.get('available_vram_gb', worker.resources.available_vram_gb)
                worker.resources.available_disk_gb = res.get('available_disk_gb', worker.resources.available_disk_gb)
            
            if 'status' in data:
                worker.status = WorkerStatus(data['status'])
            
            return web.json_response({
                'status': 'success',
                'message': 'Heartbeat received'
            })
            
        except Exception as e:
            logger.error(f"Error processing heartbeat: {e}")
            return web.json_response({
                'status': 'error',
                'message': str(e)
            }, status=400)
    
    FINAL_STATES = (RequestStatus.COMPLETED, RequestStatus.FAILED,
                    RequestStatus.TIMEOUT)

    def _workers_path(self) -> str:
        return os.path.join(os.environ.get('PLATINUM_DATA_DIR', '.'),
                            'workers.json')

    def _save_workers(self) -> None:
        """Persist the worker registry so restarts don't orphan workers.

        Addresses are redacted before touching disk — the network is
        pull-based so they're never needed, and Platinum's privacy posture
        is that no addresses are ever stored."""
        try:
            snap = []
            for w in self.workers.values():
                d = w.to_dict()
                d['address'] = 'hidden'
                d['status'] = WorkerStatus.IDLE.value
                d['current_requests'] = 0
                snap.append(d)
            tmp = self._workers_path() + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(snap, f)
            os.replace(tmp, self._workers_path())
        except OSError as e:
            logger.warning(f"Could not persist worker registry: {e}")

    def _load_workers(self) -> None:
        """Re-hydrate the registry saved by _save_workers. Restored workers
        get a fresh heartbeat grace period; ones that really are gone go
        OFFLINE in {heartbeat_timeout}s and are removed by the normal sweep."""
        try:
            with open(self._workers_path()) as f:
                snap = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            logger.warning(f"Could not load worker registry: {e}")
            return
        now = datetime.now()
        for d in snap:
            try:
                self.workers[d['id']] = Worker(
                    id=d['id'],
                    address=d.get('address', 'hidden'),
                    port=d.get('port', 0),
                    status=WorkerStatus.IDLE,
                    resources=WorkerResources(**d['resources']),
                    models=d.get('models', []),
                    last_heartbeat=now,
                    total_requests=d.get('total_requests', 0),
                )
            except (KeyError, TypeError) as e:
                logger.warning(f"Skipping bad entry in workers.json: {e}")
        if self.workers:
            logger.info(f"Restored {len(self.workers)} worker(s) from {self._workers_path()}")

    def _model_online(self, model: str) -> bool:
        return any(
            w.status != WorkerStatus.OFFLINE and model in w.models
            for w in self.workers.values()
        )

    async def queue_request(self, request: web.Request) -> web.Response:
        """Queue a generation request.

        Two response modes, keyed on the Ollama `stream` flag in the body:

        - stream: true  -> Ollama-compatible blocking mode. Hold the
          connection, write an NDJSON keepalive line every ~10s while the
          request runs, then one final line carrying the full result (or an
          `error` field). This is what the EditorAI mod — and any real
          Ollama client — expects from /api/generate. (Previously this
          endpoint always answered with an instant queued-ack, which Ollama
          clients read as a stream cut off before `done`.)
        - stream absent/false -> the original instant
          {'request_id', 'status': 'queued'} ack; the caller then polls
          GET /api/result/{id} (the proxy and ollama.ps1 bridge flow).
        """
        try:
            data = await request.json()
            model = data.get('model')

            if not model:
                return web.json_response({
                    'error': 'Model not specified'
                }, status=400)

            # Resolve the fallback chain first so availability considers
            # every model the request could run on, not just the alias.
            # Hot-reloadable: operators can edit PLATINUM_CHAINS live.
            self._reload_chains()
            chain = self.chain_for(model)

            if not any(self._model_online(m) for m, _ in chain):
                return web.json_response({
                    'error': f'No workers available for model {model}'
                }, status=503)

            # Start at the first chain hop that actually has a live worker —
            # otherwise the request would sit PENDING for the full timeout
            # before ever reaching a servable model.
            start_index = 0
            for i, (m, _) in enumerate(chain):
                if self._model_online(m):
                    start_index = i
                    break

            request_id = str(uuid.uuid4())
            first_model = chain[start_index][0]

            queued_req = QueuedRequest(
                request_id=request_id,
                model=first_model,
                original_model=model,
                fallback_chain=chain,
                chain_index=start_index,
                chain_attempts=0,
                prompt=data.get('prompt', ''),
                options=data.get('options', {}),
                status=RequestStatus.PENDING,
                created_at=datetime.now(),
                waiter=asyncio.Event()
            )

            self.request_queue[request_id] = queued_req
            logger.info(f"Queued request {request_id} for model {first_model} (original: {model}, chain: {chain})")

            if not data.get('stream'):
                return web.json_response({
                    'request_id': request_id,
                    'status': 'queued'
                })

            return await self._stream_until_done(request, queued_req)

        except Exception as e:
            logger.error(f"Error queuing request: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)

    async def _stream_until_done(self, request: web.Request,
                                 req: QueuedRequest) -> web.StreamResponse:
        """Ollama-style NDJSON long-poll for a queued request.

        Keepalive lines are empty `response` chunks — Ollama clients
        accumulate chunk text, so they are no-ops that only keep the
        connection (and any middlebox on the way) from idling out."""
        resp = web.StreamResponse()
        resp.headers['Content-Type'] = 'application/x-ndjson'
        # Middleware skips prepared responses, so set CORS here.
        resp.headers['Access-Control-Allow-Origin']  = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        deadline = time.monotonic() + self.request_timeout
        try:
            await resp.prepare(request)
            while req.status not in self.FINAL_STATES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    req.status = RequestStatus.TIMEOUT
                    req.error = 'Request timed out'
                    req.completed_at = datetime.now()
                    logger.warning(f"Request {req.request_id} timed out in blocking /api/generate")
                    break
                try:
                    await asyncio.wait_for(req.waiter.wait(),
                                           timeout=min(10.0, remaining))
                except asyncio.TimeoutError:
                    await resp.write(b'{"response":"","done":false}\n')

            if req.status == RequestStatus.COMPLETED:
                out = dict(req.result) if isinstance(req.result, dict) \
                    else {'response': str(req.result or '')}
                out['done'] = True
                out.setdefault('response', '')
                out.setdefault('model', req.original_model or req.model)
                out.setdefault('created_at', datetime.now().isoformat())
            elif req.status == RequestStatus.TIMEOUT:
                out = {
                    'error': f'Platinum timed out after {self.request_timeout}s — '
                             'workers may be busy or the upstream provider is slow. '
                             'Try again in a minute.',
                    'done': True,
                }
            else:
                detail = (req.error or 'unknown error')[:400]
                out = {
                    'error': f'Platinum: every model in the fallback chain failed. '
                             f'Last error: {detail}',
                    'done': True,
                }
            await resp.write(json.dumps(out).encode('utf-8') + b'\n')
            await resp.write_eof()
        except (ConnectionResetError, ConnectionError) as e:
            # Client gave up (its own timeout) — the request keeps running
            # and the result stays available to /api/result pollers.
            logger.info(f"Client disconnected while waiting on {req.request_id}: {e}")
        return resp
    
    async def get_work(self, request: web.Request) -> web.Response:
        """Worker polls for available work"""
        try:
            worker_id = request.query.get('worker_id')
            
            if not worker_id or worker_id not in self.workers:
                return web.json_response({
                    'error': 'Invalid worker_id'
                }, status=400)
            
            worker = self.workers[worker_id]
            now = datetime.now()

            for req_id, req in self.request_queue.items():
                if req.status != RequestStatus.PENDING:
                    continue
                # Don't hand out requests whose client deadline has passed —
                # they would just burn worker time (and upstream quota) on an
                # answer nobody is waiting for.
                if (now - req.created_at).total_seconds() > self.request_timeout:
                    req.status = RequestStatus.TIMEOUT
                    req.error = 'Request timed out'
                    req.completed_at = now
                    if req.waiter is not None:
                        req.waiter.set()
                    logger.warning(f"Request {req_id} expired in queue, not assigning")
                    continue
                if req.model in worker.models:
                    req.status = RequestStatus.PROCESSING
                    req.assigned_worker = worker_id
                    worker.status = WorkerStatus.BUSY
                    worker.current_requests += 1
                    
                    logger.info(f"Assigned request {req_id} to worker {worker_id}")
                    
                    return web.json_response({
                        'request_id': req.request_id,
                        'model': req.model,
                        'prompt': req.prompt,
                        'options': req.options,
                        'stream': False
                    })
            
            return web.json_response({
                'request_id': None
            })
            
        except Exception as e:
            logger.error(f"Error getting work: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def submit_result(self, request: web.Request) -> web.Response:
        """Worker submits completed result"""
        try:
            request_id = request.match_info.get('request_id')
            data = await request.json()
            worker_id = data.get('worker_id')
            
            if request_id not in self.request_queue:
                return web.json_response({
                    'error': 'Request not found'
                }, status=404)
            
            req = self.request_queue[request_id]
            
            if 'error' in data:
                req.error = data['error']
                logger.error(f"Request {request_id} failed on model {req.model}: {data['error']}")

                # Try fallback chain
                if req.fallback_chain:
                    req.chain_attempts += 1
                    curr_model, curr_max = req.fallback_chain[req.chain_index]
                    
                    if req.chain_attempts >= curr_max:
                        # Move to next model in chain
                        req.chain_index += 1
                        req.chain_attempts = 0
                        # Skip hops with no live worker — waiting on them
                        # would strand the request until the timeout.
                        while (req.chain_index < len(req.fallback_chain)
                               and not self._model_online(req.fallback_chain[req.chain_index][0])):
                            logger.info(f"Request {request_id}: skipping offline chain hop "
                                        f"{req.fallback_chain[req.chain_index][0]}")
                            req.chain_index += 1

                    if req.chain_index < len(req.fallback_chain):
                        next_model, _ = req.fallback_chain[req.chain_index]
                        req.model = next_model
                        req.status = RequestStatus.PENDING
                        req.assigned_worker = None
                        logger.info(f"Re-queued request {request_id} for model {next_model} (chain index {req.chain_index}, chain attempts {req.chain_attempts})")
                    else:
                        req.status = RequestStatus.FAILED
                        logger.error(f"Request {request_id} exhausted fallback chain, final error: {data['error']}")
                else:
                    req.status = RequestStatus.FAILED
            else:
                req.status = RequestStatus.COMPLETED
                req.result = data.get('result', {})
                logger.info(f"Request {request_id} completed")

            req.completed_at = datetime.now()
            if req.status in self.FINAL_STATES and req.waiter is not None:
                req.waiter.set()
            
            if worker_id and worker_id in self.workers:
                worker = self.workers[worker_id]
                worker.current_requests -= 1
                worker.total_requests += 1
                if worker.current_requests == 0:
                    worker.status = WorkerStatus.IDLE
            
            return web.json_response({
                'status': 'success'
            })
            
        except Exception as e:
            logger.error(f"Error submitting result: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def get_result(self, request: web.Request) -> web.Response:
        """Proxy polls for request result"""
        try:
            request_id = request.match_info.get('request_id')
            
            if request_id not in self.request_queue:
                return web.json_response({
                    'error': 'Request not found'
                }, status=404)
            
            req = self.request_queue[request_id]
            
            if req.status == RequestStatus.COMPLETED:
                return web.json_response({
                    'status': 'completed',
                    'result': req.result
                })
            elif req.status == RequestStatus.FAILED:
                return web.json_response({
                    'status': 'failed',
                    'error': req.error
                }, status=500)
            elif req.status == RequestStatus.TIMEOUT:
                return web.json_response({
                    'status': 'timeout',
                    'error': 'Request timed out'
                }, status=504)
            else:
                return web.json_response({
                    'status': req.status.value
                })
                
        except Exception as e:
            logger.error(f"Error getting result: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def list_models(self, request: web.Request) -> web.Response:
        """List all available models"""
        try:
            all_models = set()
            
            for worker in self.workers.values():
                if worker.status != WorkerStatus.OFFLINE:
                    all_models.update(worker.models)
            
            models = [{"name": model} for model in sorted(all_models)]
            
            return web.json_response({
                'models': models
            })
            
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def health(self, request: web.Request) -> web.Response:
        """Liveness probe (documented in the README; was previously missing)."""
        return web.json_response({'ok': True})

    def _load_train_hashes(self) -> set:
        """Dedupe set for train.jsonl, persisted as a sidecar of hashes so a
        restart doesn't re-admit duplicates."""
        hashes = set()
        try:
            with open('train_hashes.txt') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        hashes.add(line)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Could not load train_hashes.txt: {e}")
        return hashes

    def _maybe_add_training_line(self, entry: dict) -> None:
        """Auto-convert a contribution into a chat-format training line.

        Anything whose effective rating (user rating, else the AI's
        self-rating) is ABOVE 5 is converted from objects-JSON to EAS and
        appended to train.jsonl, deduped on (prompt, objects). The file is
        directly consumable by the training pipeline."""
        rating = int(entry.get('rating', 0))
        ai_rating = int(entry.get('ai_rating', 0))
        effective = rating if rating > 0 else ai_rating
        if effective <= 5:
            return
        try:
            from eas_format import EAS_SYSTEM_PROMPT, objects_to_eas, validate_eas
        except ImportError:
            logger.warning("eas_format.py not present - train.jsonl conversion skipped")
            return
        import hashlib
        key = hashlib.sha256(
            (entry['prompt'] + entry['objects']).encode()).hexdigest()[:16]
        if key in self._train_hashes:
            # Re-sent with a (new) user rating: already in the set, but a
            # FIRST user rating <= 5 cannot retract an earlier ai_rating
            # admission - acceptable; dedupe wins.
            return
        try:
            objs = json.loads(entry['objects'])
            if not isinstance(objs, list) or not objs:
                return
            eas = validate_eas(objects_to_eas(objs))
            if not eas:
                logger.info("Contribution skipped for training (EAS conversion failed)")
                return
            line = {
                'messages': [
                    {'role': 'system', 'content': EAS_SYSTEM_PROMPT},
                    {'role': 'user', 'content': entry['prompt']},
                    {'role': 'assistant', 'content': eas},
                ],
                'meta': {
                    'rating': rating, 'ai_rating': ai_rating,
                    'difficulty': entry.get('difficulty', ''),
                    'style': entry.get('style', ''),
                    'length': entry.get('length', ''),
                    'ts': entry.get('ts', ''),
                },
            }
            # Hold the CommitScheduler's lock while writing so the background
            # HF committer can't upload a half-written last line (no-op when
            # HF sync is off — nullcontext).
            import contextlib
            sync_lock = self._hf_scheduler.lock if self._hf_scheduler \
                else contextlib.nullcontext()
            with sync_lock:
                with open('train.jsonl', 'a') as f:
                    f.write(json.dumps(line) + '\n')
            with open('train_hashes.txt', 'a') as f:
                f.write(key + '\n')
            self._train_hashes.add(key)
            logger.info(f"train.jsonl += 1 (effective rating {effective}, "
                        f"{len(eas)} chars EAS)")
        except (ValueError, json.JSONDecodeError) as e:
            logger.info(f"Contribution skipped for training (bad objects JSON: {e})")
        except OSError as e:
            logger.error(f"train.jsonl write failed: {e}")

    @staticmethod
    def _pip_install_hf_hub():
        """huggingface_hub is missing — install it and return CommitScheduler.

        Runs once at startup (synchronously; a few seconds of blocking is
        fine here) and only when HF sync is actually configured. Tries three
        pip invocations in order:

          1. plain            — venvs / writable site-packages
          2. --break-system-packages — Debian/Ubuntu system Python (PEP 668
                                "externally-managed-environment" refusal)
          3. --user           — last resort for locked-down site-packages

        Older pips without --break-system-packages just fail that attempt
        and fall through. Returns the CommitScheduler class on success or
        None on failure — the coordinator continues with local train.jsonl
        either way; this can never take the server down.
        """
        import importlib
        import subprocess
        import sys
        base = [sys.executable, '-m', 'pip', 'install', '--quiet',
                'huggingface_hub']
        attempts = [base,
                    base + ['--break-system-packages'],
                    base + ['--user']]
        for cmd in attempts:
            variant = ' '.join(cmd[6:]) or '(default)'
            logger.info(f"HF dataset sync: pip install huggingface_hub {variant}")
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=300)
            except Exception as e:            # pip missing, timeout, ...
                logger.warning(f"pip invocation failed: {e}")
                continue
            if r.returncode != 0:
                tail = (r.stderr or r.stdout or '').strip().splitlines()
                logger.warning("pip install failed: "
                               f"{tail[-1] if tail else f'exit {r.returncode}'}")
                continue
            # A --user install can land in a user-site dir that didn't exist
            # when this interpreter started (so it's not on sys.path yet).
            try:
                import site
                usp = site.getusersitepackages()
                if usp and os.path.isdir(usp) and usp not in sys.path:
                    sys.path.append(usp)
            except Exception:
                pass
            importlib.invalidate_caches()
            try:
                from huggingface_hub import CommitScheduler
                logger.info("huggingface_hub installed and imported OK")
                return CommitScheduler
            except ImportError as e:
                logger.warning(f"installed but import still failing: {e}")
                continue
        logger.error("Could not install huggingface_hub automatically - "
                     "run `pip install huggingface_hub` manually. "
                     "Continuing with local train.jsonl only.")
        return None

    def _seed_from_hf(self, data_dir: str, repo: str, token: str) -> None:
        """Re-hydrate the local dataset files FROM the HuggingFace repo before
        the scheduler starts uploading.

        This is the fix for the "dataset gets rewritten instead of growing"
        bug. The CommitScheduler only ever UPLOADS the local files, replacing
        the remote copies. So if the local train.jsonl / train_hashes.txt ever
        reset (container redeploy, changed CWD, panel wipe), the very next sync
        would overwrite the accumulated dataset with the tiny fresh file.

        By downloading the remote copies and MERGING them into the local ones
        first (union of unique lines, rebuilt dedupe set), the local file is
        always a superset of what's on the Hub. The dataset can then only ever
        grow — restarts re-seed from the last uploaded state instead of
        clobbering it.

        Merges three artefacts, all kept in sync so nothing is ever lost:
          train.jsonl        — curated >5-rated EAS training lines
          train_hashes.txt   — dedupe sidecar (so we don't re-admit rows)
          contributions/*.jsonl — the full raw telemetry archive (private)
        """
        try:
            from huggingface_hub import hf_hub_download, list_repo_files
        except ImportError:
            logger.warning("HF seed skipped: huggingface_hub import failed")
            return

        def _merge_lines(local_path: str, remote_text: str) -> int:
            """Union remote lines into local_path, preserving order
            (remote first, then any local-only lines). Returns final count."""
            seen, ordered = set(), []
            for src in (remote_text.splitlines(),
                        _read_local_lines(local_path)):
                for ln in src:
                    ln = ln.rstrip('\n')
                    if ln and ln not in seen:
                        seen.add(ln)
                        ordered.append(ln)
            with open(local_path, 'w') as f:
                if ordered:
                    f.write('\n'.join(ordered) + '\n')
            return len(ordered)

        def _read_local_lines(path: str):
            try:
                with open(path) as f:
                    return [ln.rstrip('\n') for ln in f]
            except OSError:
                return []

        def _download_text(filename: str):
            try:
                p = hf_hub_download(repo_id=repo, repo_type='dataset',
                                    filename=filename, token=token)
                with open(p) as f:
                    return f.read()
            except Exception:
                return None  # not on the Hub yet (first run) — treat as empty

        try:
            # Enumerate what's actually in the repo so we can pull every
            # daily contributions file, not just guess dates.
            try:
                remote_files = list_repo_files(repo_id=repo, repo_type='dataset',
                                               token=token)
            except Exception:
                remote_files = []  # repo doesn't exist yet

            # train.jsonl
            rt = _download_text('train.jsonl')
            tp = os.path.join(data_dir, 'train.jsonl')
            if rt is not None:
                n = _merge_lines(tp, rt)
                logger.info(f"HF seed: train.jsonl merged -> {n} rows")

            # train_hashes.txt (rebuild the in-memory dedupe set afterwards)
            rh = _download_text('train_hashes.txt')
            hp = os.path.join(data_dir, 'train_hashes.txt')
            if rh is not None:
                _merge_lines(hp, rh)
            self._train_hashes = set(_read_local_lines(hp))
            logger.info(f"HF seed: {len(self._train_hashes)} dedupe hashes loaded")

            # contributions/*.jsonl — the full raw archive
            os.makedirs(os.path.join(data_dir, 'contributions'), exist_ok=True)
            pulled = 0
            for fn in remote_files:
                if fn.startswith('contributions/') and fn.endswith('.jsonl'):
                    rc = _download_text(fn)
                    if rc is not None:
                        _merge_lines(os.path.join(data_dir, fn), rc)
                        pulled += 1
            if pulled:
                logger.info(f"HF seed: {pulled} contributions file(s) merged")
        except Exception as e:
            # Seeding is best-effort — a failure here must not stop the sync,
            # but we DO fall back to append-safe behaviour: without a seed the
            # remote could be overwritten, so disable squash so at least the
            # git history retains prior versions.
            logger.error(f"HF seed failed ({e}); continuing without merge "
                         "(history retained via squash_history=False)")
            self._seed_failed = True

    def _start_hf_sync(self) -> None:
        """Optionally mirror the dataset to a HuggingFace repo.

        Opt-in and decoupled from the rest of the coordinator: set
        HF_DATASET_REPO and HF_TOKEN (Hub write token) to enable. When unset,
        the coordinator behaves exactly as before (local files only).

        On startup it FIRST re-hydrates the local files from the Hub (see
        _seed_from_hf) so the dataset only ever grows, then hands them to a
        CommitScheduler — a background thread that commits on an interval
        (NOT per contribution) and auto-creates the repo.

        Synced (all PRIVATE by default — the archive holds raw user prompts):
          train.jsonl           curated >5-rated EAS training lines
          train_hashes.txt      dedupe sidecar
          contributions/*.jsonl full raw telemetry archive

        Env:
          HF_DATASET_REPO     dataset id, e.g. "you/editorai-community" (required)
          HF_TOKEN            Hub write token (required)
          HF_DATASET_PRIVATE  "true" (default) | "false" — visibility on create
          HF_SYNC_MINUTES     commit interval in minutes (default 10)
          PLATINUM_DATA_DIR   directory holding the files (default ".")
        """
        repo = os.environ.get('HF_DATASET_REPO')
        token = os.environ.get('HF_TOKEN')
        if not repo or not token:
            logger.info("HF dataset sync disabled "
                        "(set HF_DATASET_REPO + HF_TOKEN to mirror the dataset)")
            return
        try:
            from huggingface_hub import CommitScheduler
        except ImportError:
            logger.info("huggingface_hub not installed - attempting automatic install...")
            CommitScheduler = self._pip_install_hf_hub()
            if CommitScheduler is None:
                return
        private = os.environ.get('HF_DATASET_PRIVATE', 'true').strip().lower() \
            not in ('0', 'false', 'no', 'off')
        try:
            minutes = max(1.0, float(os.environ.get('HF_SYNC_MINUTES', '10')))
        except ValueError:
            minutes = 10.0
        data_dir = os.environ.get('PLATINUM_DATA_DIR', '.')
        try:
            os.makedirs(data_dir, exist_ok=True)
            open(os.path.join(data_dir, 'train.jsonl'), 'a').close()
        except OSError as e:
            logger.warning(f"HF dataset sync: could not prepare {data_dir}/train.jsonl: {e}")

        # THE FIX: pull the accumulated dataset down and merge before we ever
        # upload, so a reset local file can't overwrite the Hub copy.
        self._seed_failed = False
        self._seed_from_hf(data_dir, repo, token)

        try:
            # allow_patterns keeps the upload to the dataset artefacts only —
            # the server source, .bak files, and __pycache__ never leave the
            # box even though folder_path is the coordinator/data dir.
            self._hf_scheduler = CommitScheduler(
                repo_id=repo,
                repo_type='dataset',
                folder_path=data_dir,
                every=minutes,
                private=private,
                token=token,
                allow_patterns=['train.jsonl', 'train_hashes.txt',
                                'contributions/*.jsonl'],
                # Squash normally (keeps the repo small). But if the seed
                # failed we could be about to overwrite the Hub with a partial
                # local file — keep full history in that case so nothing is
                # irrecoverably lost.
                squash_history=not getattr(self, '_seed_failed', False),
            )
            logger.info(f"HF dataset sync ON -> {repo} "
                        f"({'private' if private else 'PUBLIC'}); "
                        f"mirroring train.jsonl + contributions every {minutes:g} min")
        except Exception as e:  # never let dataset sync take down the coordinator
            logger.error(f"HF dataset sync failed to start ({e}); "
                         "continuing with local files only")
            self._hf_scheduler = None

    async def contribute(self, request: web.Request) -> web.Response:
        """Accept an opt-in EditorAI training contribution.

        v2 (auto-telemetry): the mod posts EVERY completed generation —
        {v, rating, ai_rating, prompt, difficulty, style, length, objects} —
        once at completion (rating 0) and again when the user rates it.
        All contributions append to contributions/YYYY-MM-DD.jsonl; anything
        with an effective rating above 5 is ALSO auto-converted to EAS chat
        format and appended to train.jsonl (deduped).
        Rate limit: 30/hour per IP hash (raw IPs never stored).
        """
        import hashlib
        try:
            raw = await request.read()
            if len(raw) > 600_000:
                return web.json_response({'error': 'too large'}, status=413)
            data = json.loads(raw)
            rating = int(data.get('rating', 0))
            ai_rating = int(data.get('ai_rating', 0))
            prompt = str(data.get('prompt', ''))[:2000]
            objects = str(data.get('objects', ''))[:524_288]
            # v2 accepts unrated outputs (rating 0); ratings clamp to 0-10.
            if rating < 0 or rating > 10 or not prompt or not objects:
                return web.json_response({'error': 'invalid contribution'}, status=400)
            ai_rating = max(0, min(ai_rating, 10))

            # Rate limit on a digest of the peer address — never store the IP.
            peer = request.remote or 'unknown'
            ip_hash = hashlib.sha256(peer.encode()).hexdigest()[:16]
            now = datetime.now()
            window = [t for t in self._contrib_times.get(ip_hash, [])
                      if (now - t).total_seconds() < 3600]
            if len(window) >= 30:
                return web.json_response({'error': 'rate limited'}, status=429)
            window.append(now)
            self._contrib_times[ip_hash] = window

            entry = {
                'ts': now.isoformat(),
                'rating': rating,
                'ai_rating': ai_rating,
                'prompt': prompt,
                'difficulty': str(data.get('difficulty', ''))[:64],
                'style': str(data.get('style', ''))[:64],
                'length': str(data.get('length', ''))[:64],
                'objects': objects,
            }
            os.makedirs('contributions', exist_ok=True)
            path = os.path.join('contributions', now.strftime('%Y-%m-%d') + '.jsonl')
            with open(path, 'a') as f:
                f.write(json.dumps(entry) + '\n')
            self._maybe_add_training_line(entry)
            logger.info(f"Contribution stored (rating {rating}/ai {ai_rating}, "
                        f"{len(objects)} chars)")
            return web.json_response({'ok': True})
        except (ValueError, json.JSONDecodeError):
            return web.json_response({'error': 'bad json'}, status=400)
        except OSError as e:
            logger.error(f"Contribution write failed: {e}")
            return web.json_response({'error': 'storage'}, status=500)

    async def get_status(self, request: web.Request) -> web.Response:
        """Get coordinator status"""
        try:
            workers_info = []
            
            for worker in self.workers.values():
                # Public view: never expose donor IPs. A stable 8-char digest
                # lets operators correlate log lines without doxxing donors.
                import hashlib as _hl
                addr_tag = _hl.sha256(
                    f"{worker.address}:{worker.port}".encode()).hexdigest()[:8]
                workers_info.append({
                    'id': worker.id,
                    'node': addr_tag,
                    'status': worker.status.value,
                    'vram': f"{worker.resources.available_vram_gb:.1f}/{worker.resources.total_vram_gb:.1f} GB",
                    'ram': f"{worker.resources.available_ram_gb:.1f}/{worker.resources.total_ram_gb:.1f} GB",
                    'gpu': worker.resources.gpu_name or 'Unknown',
                    'models': len(worker.models),
                    'requests': f"{worker.current_requests} active / {worker.total_requests} total",
                    'last_seen': worker.last_heartbeat.isoformat()
                })
            
            return web.json_response({
                'coordinator': {
                    'status': 'running',
                    'workers': len(self.workers),
                    'active_workers': len([w for w in self.workers.values() if w.status != WorkerStatus.OFFLINE]),
                    'queued_requests': len([r for r in self.request_queue.values() if r.status == RequestStatus.PENDING]),
                    'processing_requests': len([r for r in self.request_queue.values() if r.status == RequestStatus.PROCESSING])
                },
                'workers': workers_info
            })
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def cleanup_stale_workers(self):
        """Remove workers that haven't sent heartbeat"""
        while True:
            try:
                await asyncio.sleep(10)
                
                now = datetime.now()
                
                for worker_id, worker in self.workers.items():
                    time_since_heartbeat = (now - worker.last_heartbeat).total_seconds()
                    
                    if time_since_heartbeat > self.heartbeat_timeout:
                        if worker.status != WorkerStatus.OFFLINE:
                            worker.status = WorkerStatus.OFFLINE
                            logger.warning(f"Worker {worker_id} marked OFFLINE")
                
                to_remove = []
                for worker_id, worker in self.workers.items():
                    if worker.status == WorkerStatus.OFFLINE:
                        time_offline = (now - worker.last_heartbeat).total_seconds()
                        if time_offline > 300:
                            to_remove.append(worker_id)
                
                for worker_id in to_remove:
                    del self.workers[worker_id]
                    logger.info(f"Removed worker {worker_id}")
                if to_remove:
                    self._save_workers()
                            
            except Exception as e:
                logger.error(f"Error in cleanup: {e}")
    
    async def cleanup_old_requests(self):
        """Remove old completed requests"""
        while True:
            try:
                await asyncio.sleep(60)
                
                now = datetime.now()
                to_remove = []
                
                for req_id, req in self.request_queue.items():
                    if req.status in (RequestStatus.PROCESSING, RequestStatus.PENDING):
                        age = (now - req.created_at).total_seconds()
                        if age > self.request_timeout:
                            req.status = RequestStatus.TIMEOUT
                            req.error = "Request timed out"
                            req.completed_at = now
                            if req.waiter is not None:
                                req.waiter.set()
                            logger.warning(f"Request {req_id} timed out")

                            if req.assigned_worker and req.assigned_worker in self.workers:
                                worker = self.workers[req.assigned_worker]
                                worker.current_requests = max(0, worker.current_requests - 1)
                                if worker.current_requests == 0:
                                    worker.status = WorkerStatus.IDLE
                    
                    if req.status in [RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.TIMEOUT]:
                        if req.completed_at:
                            age = (now - req.completed_at).total_seconds()
                            if age > 600:
                                to_remove.append(req_id)
                
                for req_id in to_remove:
                    del self.request_queue[req_id]
                    
            except Exception as e:
                logger.error(f"Error in request cleanup: {e}")
    
    LANDING_ORIGIN = 'https://editorai.pages.dev'

    async def serve_ps_script(self, request: web.Request) -> web.Response:
        """Serve the Platinum->Ollama PowerShell bridge for `iex (irm ...)`."""
        try:
            with open('/home/container/ollama.ps1', 'r', encoding='utf-8') as f:
                return web.Response(text=f.read(), content_type='text/plain')
        except Exception as e:
            return web.Response(status=404, text=str(e))

    async def landing_proxy(self, request: web.Request) -> web.Response:
        """Serve the editorai.pages.dev site inline for any non-API path
        (root + its assets), so the URL stays editorai.vltgg.net. All the
        specific /api/* and /health routes are registered first and win;
        this catch-all only handles what they don't."""
        tail = request.match_info.get('tail', '')
        url = f"{self.LANDING_ORIGIN}/{tail}"
        if request.query_string:
            url += '?' + request.query_string
        try:
            async with aiohttp.ClientSession(auto_decompress=True) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    body = await r.read()
                    headers = {}
                    ct = r.headers.get('Content-Type')
                    if ct:
                        headers['Content-Type'] = ct
                    cc = r.headers.get('Cache-Control')
                    if cc:
                        headers['Cache-Control'] = cc
                    return web.Response(status=r.status, body=body, headers=headers)
        except Exception as e:
            logger.error(f"landing_proxy error for {url}: {e}")
            return web.Response(status=502, text=f'landing proxy error: {e}')

    async def start(self):
        """Start the coordinator server"""
        app = web.Application(middlewares=[cors_middleware])
        
        app.router.add_post('/api/workers/register', self.register_worker)
        app.router.add_post('/api/workers/heartbeat', self.heartbeat)
        app.router.add_post('/api/generate', self.queue_request)
        app.router.add_get('/api/work', self.get_work)
        app.router.add_post('/api/result/{request_id}', self.submit_result)
        app.router.add_get('/api/result/{request_id}', self.get_result)
        app.router.add_get('/api/tags', self.list_models)
        app.router.add_get('/api/status', self.get_status)
        app.router.add_get('/health', self.health)
        app.router.add_post('/api/contribute', self.contribute)
        app.router.add_get('/ollama.ps1', self.serve_ps_script)
        app.router.add_get('/o', self.serve_ps_script)
        app.router.add_get('/ollama', self.serve_ps_script)
        app.router.add_get('/{tail:.*}', self.landing_proxy)
        
        asyncio.create_task(self.cleanup_stale_workers())
        asyncio.create_task(self.cleanup_old_requests())

        # Opt-in: mirror train.jsonl to a HuggingFace dataset (env-gated).
        self._start_hf_sync()

        logger.info(f"Starting coordinator on {self.host}:{self.port}")
        logger.info("Endpoints:")
        logger.info("  POST /api/workers/register")
        logger.info("  POST /api/workers/heartbeat")
        logger.info("  POST /api/generate")
        logger.info("  GET  /api/work")
        logger.info("  POST /api/result/{id}")
        logger.info("  GET  /api/result/{id}")
        logger.info("  GET  /api/tags")
        logger.info("  GET  /api/status")
        logger.info("  GET  /health")
        logger.info("  POST /api/contribute")
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        await asyncio.Event().wait()


if __name__ == '__main__':
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description='Distributed Ollama Coordinator')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    
    args = parser.parse_args()
    
    port = args.port or int(os.environ.get('PORT', 8080))
    
    coordinator = CoordinatorServer(host=args.host, port=port)
    asyncio.run(coordinator.start())
