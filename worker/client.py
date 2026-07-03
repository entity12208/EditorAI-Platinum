#!/usr/bin/env python3
"""
Platinum Worker Client
Runs on contributor machines to donate compute to the EditorAI Platinum
network. Supports several backends so you can donate more than a local Ollama:

  ollama    (default) a local Ollama server            -> /api/generate
  llamacpp  a llama.cpp server (OpenAI-compat)          -> /v1/chat/completions
  openai    any OpenAI-compatible endpoint + API key    -> /v1/chat/completions
            (this covers hosted APIs you want to share, and self-hosted
             gateways / custom endpoints)

Whatever the backend, the worker turns each job into an Ollama-style result
so the coordinator and the mod see one consistent protocol.

PRIVACY: the worker NEVER sends your IP address to the coordinator. The
network is pull-based (workers poll the coordinator; it never dials back),
so your address is not needed for routing and is never transmitted or stored.
"""

import asyncio
import getpass
import logging
import os
import subprocess
import sys
from typing import List, Optional
import aiohttp
import psutil
from dataclasses import dataclass
import uuid

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class SystemResources:
    total_ram_gb: float
    available_ram_gb: float
    total_vram_gb: float
    available_vram_gb: float
    total_disk_gb: float
    available_disk_gb: float
    cpu_count: int
    gpu_name: Optional[str] = None


class PlatinumWorker:
    def __init__(
        self,
        coordinator_url: str,
        backend: str = "ollama",
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        models: Optional[List[str]] = None,
        worker_id: Optional[str] = None,
    ):
        self.coordinator_url = coordinator_url.rstrip('/')
        self.backend = backend
        self.api_key = api_key
        self.configured_models = models or []
        self.worker_id = worker_id or str(uuid.uuid4())
        self.is_running = False

        # Resolve the backend base URL (endpoint). Defaults per backend.
        if backend == "ollama":
            self.endpoint = (endpoint or "http://localhost:11434").rstrip('/')
        elif backend == "llamacpp":
            self.endpoint = (endpoint or "http://localhost:8080").rstrip('/')
        elif backend == "openai":
            # No sane default — an OpenAI-compat endpoint must be supplied.
            self.endpoint = (endpoint or "").rstrip('/')
        else:
            raise ValueError(f"unknown backend: {backend}")

    # ── Resource probing ────────────────────────────────────────────────────
    def get_gpu_info(self):
        try:
            result = subprocess.run(
                ['nvidia-smi',
                 '--query-gpu=name,memory.total,memory.free',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if lines:
                    parts = lines[0].split(',')
                    return (parts[0].strip(),
                            float(parts[1].strip()) / 1024,
                            float(parts[2].strip()) / 1024)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"Could not get GPU info: {e}")
        return None, 0.0, 0.0

    def get_system_resources(self) -> SystemResources:
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        gpu_name, total_vram_gb, available_vram_gb = self.get_gpu_info()
        return SystemResources(
            total_ram_gb=ram.total / (1024**3),
            available_ram_gb=ram.available / (1024**3),
            total_vram_gb=total_vram_gb,
            available_vram_gb=available_vram_gb,
            total_disk_gb=disk.total / (1024**3),
            available_disk_gb=disk.free / (1024**3),
            cpu_count=psutil.cpu_count(logical=False) or 1,
            gpu_name=gpu_name,
        )

    # ── Model discovery (per backend) ──────────────────────────────────────
    async def get_models(self) -> List[str]:
        """Which model names this worker can serve.

        ollama/llamacpp: auto-enumerated from the server, unless --models is
        given (then that overrides). openai/custom: --models is authoritative
        (we can't safely enumerate an arbitrary gateway's catalogue, and the
        operator decides exactly what to expose to the network)."""
        if self.configured_models:
            return self.configured_models
        if self.backend == "ollama":
            return await self._enumerate_ollama()
        if self.backend == "llamacpp":
            return await self._enumerate_openai_compat()  # llama.cpp serves /v1/models
        if self.backend == "openai":
            # Require an explicit list — never auto-expose a paid account's
            # entire model catalogue to the whole network by accident.
            logger.error("openai backend requires --models "
                         "(the model names you want to share)")
            return []
        return []

    async def _enumerate_ollama(self) -> List[str]:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.endpoint}/api/tags",
                                 timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        return [m['name'] for m in data.get('models', [])]
                    logger.error(f"Ollama /api/tags HTTP {r.status}")
        except Exception as e:
            logger.error(f"Error connecting to Ollama at {self.endpoint}: {e}")
        return []

    async def _enumerate_openai_compat(self) -> List[str]:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.endpoint}/v1/models",
                                 headers=self._auth_headers(),
                                 timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        return [m['id'] for m in data.get('data', []) if 'id' in m]
                    logger.error(f"/v1/models HTTP {r.status}")
        except Exception as e:
            logger.error(f"Error listing models at {self.endpoint}: {e}")
        return []

    def _auth_headers(self) -> dict:
        return {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}

    # ── Coordinator registration / heartbeat ───────────────────────────────
    async def register_with_coordinator(self) -> bool:
        try:
            resources = self.get_system_resources()
            models = await self.get_models()
            if not models:
                logger.error("No models to serve. For ollama/llamacpp make "
                             "sure the server is up with a model loaded; for "
                             "openai pass --models.")
                return False

            registration_data = {
                'worker_id': self.worker_id,
                # PRIVACY: never send the real IP. The coordinator only ever
                # hashes address:port for its status page and never dials the
                # worker back (pull model), so a constant placeholder is fine.
                'address': 'hidden',
                'port': 0,
                'resources': {
                    'total_ram_gb': resources.total_ram_gb,
                    'available_ram_gb': resources.available_ram_gb,
                    'total_vram_gb': resources.total_vram_gb,
                    'available_vram_gb': resources.available_vram_gb,
                    'total_disk_gb': resources.total_disk_gb,
                    'available_disk_gb': resources.available_disk_gb,
                    'cpu_count': resources.cpu_count,
                    'gpu_name': resources.gpu_name,
                },
                'models': models,
            }
            async with aiohttp.ClientSession() as s:
                url = f"{self.coordinator_url}/api/workers/register"
                async with s.post(url, json=registration_data,
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        logger.info("Registered with coordinator "
                                    f"(backend: {self.backend})")
                        logger.info(f"Worker ID: {self.worker_id}")
                        logger.info(f"Serving models: {', '.join(models[:8])}"
                                    f"{'...' if len(models) > 8 else ''}")
                        return True
                    logger.error(f"Register failed: HTTP {r.status} - "
                                 f"{await r.text()}")
        except Exception as e:
            logger.error(f"Error registering with coordinator: {e}")
        return False

    async def send_heartbeat(self):
        while self.is_running:
            try:
                resources = self.get_system_resources()
                data = {
                    'worker_id': self.worker_id,
                    'status': 'idle',
                    'resources': {
                        'available_ram_gb': resources.available_ram_gb,
                        'available_vram_gb': resources.available_vram_gb,
                        'available_disk_gb': resources.available_disk_gb,
                    },
                }
                async with aiohttp.ClientSession() as s:
                    url = f"{self.coordinator_url}/api/workers/heartbeat"
                    async with s.post(url, json=data,
                                      timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status != 200:
                            logger.warning(f"Heartbeat HTTP {r.status}")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(10)

    # ── Work loop ──────────────────────────────────────────────────────────
    async def poll_for_work(self):
        while self.is_running:
            try:
                async with aiohttp.ClientSession() as s:
                    url = f"{self.coordinator_url}/api/work?worker_id={self.worker_id}"
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status == 200:
                            work = await r.json()
                            if work.get('request_id'):
                                logger.info(f"Received work: {work['request_id']}")
                                await self.process_work(work['request_id'], work)
                            else:
                                await asyncio.sleep(2)
                        else:
                            logger.warning(f"Get work HTTP {r.status}")
                            await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Poll error: {e}")
                await asyncio.sleep(5)

    async def process_work(self, request_id: str, work: dict):
        model = work.get('model')
        prompt = work.get('prompt')
        options = work.get('options', {})
        logger.info(f"Processing {request_id} with {model} via {self.backend}")
        try:
            if self.backend == "ollama":
                result = await self._run_ollama(model, prompt, options)
            else:
                result = await self._run_openai_compat(model, prompt, options)
            await self.submit_result(request_id, result)
        except asyncio.TimeoutError:
            await self.submit_error(request_id, "Timeout processing request")
        except Exception as e:
            logger.error(f"Error on {request_id}: {e}")
            await self.submit_error(request_id, str(e))

    async def _run_ollama(self, model, prompt, options) -> dict:
        async with aiohttp.ClientSession() as s:
            body = {'model': model, 'prompt': prompt, 'stream': False,
                    'options': options}
            async with s.post(f"{self.endpoint}/api/generate", json=body,
                              timeout=aiohttp.ClientTimeout(total=300)) as r:
                if r.status == 200:
                    return await r.json()  # already Ollama-shaped ({response,...})
                raise RuntimeError(f"Ollama HTTP {r.status}: {await r.text()}")

    async def _run_openai_compat(self, model, prompt, options) -> dict:
        """llama.cpp / openai / custom all speak /v1/chat/completions. We wrap
        the coordinator's single `prompt` string as one user message, then
        normalise the reply back into Ollama's {'response': text} shape so the
        rest of the pipeline is backend-agnostic."""
        body = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'stream': False,
        }
        # Pass through the sampling knobs the mod may have set.
        if isinstance(options, dict):
            if 'temperature' in options:
                body['temperature'] = options['temperature']
            if 'top_p' in options:
                body['top_p'] = options['top_p']
            num_predict = options.get('num_predict')
            if isinstance(num_predict, int) and num_predict > 0:
                body['max_tokens'] = num_predict
        headers = {'Content-Type': 'application/json', **self._auth_headers()}
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{self.endpoint}/v1/chat/completions",
                              json=body, headers=headers,
                              timeout=aiohttp.ClientTimeout(total=300)) as r:
                if r.status != 200:
                    raise RuntimeError(f"{self.backend} HTTP {r.status}: "
                                       f"{await r.text()}")
                data = await r.json()
                text = ''
                try:
                    text = data['choices'][0]['message']['content'] or ''
                except (KeyError, IndexError, TypeError):
                    raise RuntimeError("no content in chat-completions reply")
                # Ollama-shaped result — what the coordinator/mod expect.
                return {'model': model, 'response': text, 'done': True}

    async def submit_result(self, request_id: str, result: dict):
        try:
            async with aiohttp.ClientSession() as s:
                url = f"{self.coordinator_url}/api/result/{request_id}"
                async with s.post(url, json={'worker_id': self.worker_id,
                                             'result': result},
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        logger.info(f"Submitted result for {request_id}")
                    else:
                        logger.error(f"Submit result HTTP {r.status}")
        except Exception as e:
            logger.error(f"Error submitting result: {e}")

    async def submit_error(self, request_id: str, error: str):
        try:
            async with aiohttp.ClientSession() as s:
                url = f"{self.coordinator_url}/api/result/{request_id}"
                async with s.post(url, json={'worker_id': self.worker_id,
                                             'error': error},
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        logger.error(f"Submit error HTTP {r.status}")
        except Exception as e:
            logger.error(f"Error submitting error: {e}")

    async def _backend_reachable(self) -> bool:
        try:
            probe = (f"{self.endpoint}/api/tags" if self.backend == "ollama"
                     else f"{self.endpoint}/v1/models")
            async with aiohttp.ClientSession() as s:
                async with s.get(probe, headers=self._auth_headers(),
                                 timeout=aiohttp.ClientTimeout(total=5)) as r:
                    return r.status == 200
        except Exception:
            return False

    async def start(self):
        logger.info("=" * 60)
        logger.info("EditorAI Platinum Worker")
        logger.info("=" * 60)
        logger.info(f"Worker ID:   {self.worker_id}")
        logger.info(f"Coordinator: {self.coordinator_url}")
        logger.info(f"Backend:     {self.backend} @ {self.endpoint or '(none)'}")
        logger.info("=" * 60)

        if self.backend in ("ollama", "llamacpp"):
            logger.info(f"Checking {self.backend} server...")
            if not await self._backend_reachable():
                logger.error(f"{self.backend} not reachable at {self.endpoint}")
                logger.error("Start the server and retry.")
                return
            logger.info(f"✓ {self.backend} is running")

        logger.info("Registering with coordinator...")
        if not await self.register_with_coordinator():
            logger.error("Registration failed. Exiting.")
            return

        self.is_running = True
        hb = asyncio.create_task(self.send_heartbeat())
        wk = asyncio.create_task(self.poll_for_work())
        logger.info("=" * 60)
        logger.info("Worker active - donating compute to the network!")
        logger.info("Press Ctrl+C to stop.")
        logger.info("=" * 60)
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("\nShutting down worker...")
            self.is_running = False
            hb.cancel()
            wk.cancel()
            logger.info("Worker stopped. Thank you for contributing!")


async def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='EditorAI Platinum Worker - donate compute to the network',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local Ollama (default)
  python client.py

  # A llama.cpp server
  python client.py --backend llamacpp --endpoint http://localhost:8080

  # Share a hosted / custom OpenAI-compatible endpoint under chosen names
  python client.py --backend openai \\
      --endpoint https://api.example.com \\
      --models glm-4.7-flash,glm-4.5-flash
  # (you'll be prompted for the API key unless --api-key / EDITORAI_WORKER_API_KEY)
""")
    parser.add_argument('--coordinator',
                        default='https://ollama-coordinator.onrender.com',
                        help='Coordinator server URL')
    parser.add_argument('--backend', choices=['ollama', 'llamacpp', 'openai'],
                        default='ollama',
                        help='Compute backend to donate (default: ollama)')
    parser.add_argument('--endpoint',
                        help='Backend base URL (defaults: ollama '
                             'http://localhost:11434, llamacpp '
                             'http://localhost:8080; required for openai)')
    parser.add_argument('--api-key',
                        help='API key for the openai backend. If omitted you '
                             'are prompted (or set EDITORAI_WORKER_API_KEY).')
    parser.add_argument('--models',
                        help='Comma-separated model names to advertise. '
                             'Required for openai; overrides auto-enumeration '
                             'for ollama/llamacpp.')
    # Back-compat aliases from the old Ollama-only client.
    parser.add_argument('--ollama-host', help='(compat) Ollama host')
    parser.add_argument('--ollama-port', type=int, help='(compat) Ollama port')
    parser.add_argument('--worker-port', type=int, help='(compat, ignored)')
    parser.add_argument('--worker-id', help='Custom worker ID')
    args = parser.parse_args()

    # Resolve endpoint back-compat: old --ollama-host/--ollama-port.
    endpoint = args.endpoint
    if not endpoint and args.backend == 'ollama' and (args.ollama_host or args.ollama_port):
        host = args.ollama_host or 'localhost'
        port = args.ollama_port or 11434
        endpoint = f"http://{host}:{port}"

    models = [m.strip() for m in args.models.split(',')] if args.models else None

    # API key: flag > env > interactive prompt (openai only).
    api_key = args.api_key or os.environ.get('EDITORAI_WORKER_API_KEY')
    if args.backend == 'openai' and not api_key:
        try:
            api_key = getpass.getpass(
                "API key for this endpoint (hidden, blank = no auth): ").strip() or None
        except (EOFError, KeyboardInterrupt):
            api_key = None

    worker = PlatinumWorker(
        coordinator_url=args.coordinator,
        backend=args.backend,
        endpoint=endpoint,
        api_key=api_key,
        models=models,
        worker_id=args.worker_id,
    )
    await worker.start()


if __name__ == '__main__':
    asyncio.run(main())
