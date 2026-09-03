#!/usr/bin/env python3
"""
Public Ollama Proxy
Provides a public URL interface that forwards to the coordinator
This makes the distributed Ollama cluster accessible via a single public endpoint
"""

import asyncio
import json
import logging
import os
from aiohttp import web, ClientSession, ClientTimeout
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OllamaProxy:
    def __init__(self, coordinator_url: str, host: str = "0.0.0.0", port: int = 11434):
        self.coordinator_url = coordinator_url.rstrip('/')
        self.host = host
        self.port = port
        self.request_count = 0
        
    async def proxy_generate(self, request: web.Request) -> web.Response:
        """Proxy /api/generate to the coordinator.

        Two modes, keyed on the Ollama `stream` flag, matching what the
        coordinator itself does:

        - stream: true  -> pipe the coordinator's NDJSON straight through, so
          the caller sees tokens as they are generated (real Ollama
          behaviour). Previously the proxy stripped the flag and answered with
          one buffered JSON object, which is why nothing ever streamed
          through this port.
        - stream absent/false -> the original buffered single JSON object
          (queue, then poll GET /api/result/{id}), unchanged.
        """
        try:
            data = await request.json()
        except Exception as e:
            return web.json_response({'error': f'bad json: {e}'}, status=400)

        self.request_count += 1
        logger.info(f"Request #{self.request_count}: Generating with model "
                    f"'{data.get('model', 'unknown')}'"
                    f"{' (streaming)' if data.get('stream') else ''}")

        if data.get('stream'):
            return await self._proxy_stream(request, data)
        return await self._proxy_buffered(data)

    async def _proxy_stream(self, request: web.Request,
                            data: dict) -> web.StreamResponse:
        """Pass the coordinator's NDJSON token stream through untouched."""
        url = f"{self.coordinator_url}/api/generate"
        resp = None
        try:
            async with ClientSession() as session:
                async with session.post(
                        url, json=data,
                        timeout=ClientTimeout(total=None, sock_connect=60,
                                              sock_read=120)) as upstream:
                    if upstream.status != 200:
                        body = await upstream.text()
                        logger.error(f"Request #{self.request_count}: "
                                     f"coordinator HTTP {upstream.status}")
                        return web.json_response(
                            {'error': body[:500] or 'coordinator error'},
                            status=upstream.status)
                    resp = web.StreamResponse()
                    resp.headers['Content-Type'] = 'application/x-ndjson'
                    resp.headers['Access-Control-Allow-Origin'] = '*'
                    resp.headers['Access-Control-Allow-Methods'] = \
                        'GET, POST, OPTIONS'
                    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
                    await resp.prepare(request)
                    async for chunk in upstream.content.iter_any():
                        await resp.write(chunk)
                    await resp.write_eof()
                    logger.info(f"Request #{self.request_count}: stream done")
                    return resp
        except Exception as e:
            logger.error(f"Request #{self.request_count}: stream error - {e}")
            if resp is not None and resp.prepared:
                # Headers already sent: close with an Ollama-shaped error line.
                try:
                    await resp.write(json.dumps({'error': str(e),
                                                 'done': True}).encode() + b'\n')
                    await resp.write_eof()
                except Exception:
                    pass
                return resp
            return web.json_response({'error': str(e)}, status=502)

    async def _proxy_buffered(self, data: dict) -> web.Response:
        """Original queue + poll flow, returning one Ollama result object."""
        try:
            # stream:true would make the coordinator long-poll NDJSON at us
            # instead of returning the request_id ack, so keep it off here.
            data['stream'] = False

            async with ClientSession() as session:
                # Step 1: Queue the request - retry up to 5 times to handle
                # coordinator waking up from Render free tier sleep (~30s)
                url = f"{self.coordinator_url}/api/generate"
                queue_result = None
                last_error = None
                
                for attempt in range(5):
                    try:
                        if attempt > 0:
                            wait = 15 * attempt
                            logger.info(f"Request #{self.request_count}: Retrying queue (attempt {attempt + 1}/5, waiting {wait}s for coordinator to wake)...")
                            await asyncio.sleep(wait)
                        
                        async with session.post(
                            url,
                            json=data,
                            timeout=ClientTimeout(total=60)  # 60s - enough for Render cold start
                        ) as resp:
                            if resp.status == 200:
                                queue_result = await resp.json()
                                break
                            else:
                                last_error = await resp.text()
                                logger.warning(f"Request #{self.request_count}: Queue attempt {attempt + 1} failed: HTTP {resp.status} - {last_error}")
                                
                    except asyncio.TimeoutError:
                        last_error = "Coordinator timeout (may be waking from sleep)"
                        logger.warning(f"Request #{self.request_count}: Queue attempt {attempt + 1} timed out")
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Request #{self.request_count}: Queue attempt {attempt + 1} error: {e}")
                
                if not queue_result:
                    logger.error(f"Request #{self.request_count}: All queue attempts failed: {last_error}")
                    return web.json_response({
                        'error': last_error or 'Failed to reach coordinator'
                    }, status=503)
                
                request_id = queue_result.get('request_id')
                
                if not request_id:
                    return web.json_response({
                        'error': 'No request_id returned from coordinator'
                    }, status=500)
                
                logger.info(f"Request #{self.request_count}: Queued as {request_id}")
                
                # Step 2: Poll for result (coordinator is now awake, so 15s timeout per poll is fine)
                result_url = f"{self.coordinator_url}/api/result/{request_id}"
                max_wait = 300  # 5 minutes
                poll_interval = 2  # seconds
                elapsed = 0
                
                while elapsed < max_wait:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                    
                    try:
                        async with session.get(result_url, timeout=ClientTimeout(total=15)) as resp:
                            if resp.status == 200:
                                result_data = await resp.json()
                                status = result_data.get('status')
                                
                                if status == 'completed':
                                    logger.info(f"Request #{self.request_count}: Completed in {elapsed}s")
                                    return web.json_response(result_data.get('result', {}))
                                elif status == 'failed':
                                    logger.error(f"Request #{self.request_count}: Failed - {result_data.get('error')}")
                                    return web.json_response({
                                        'error': result_data.get('error', 'Unknown error')
                                    }, status=500)
                                elif status == 'timeout':
                                    logger.error(f"Request #{self.request_count}: Timed out")
                                    return web.json_response({
                                        'error': 'Request timed out waiting for worker'
                                    }, status=504)
                                else:
                                    logger.debug(f"Request #{self.request_count}: Status = {status}, elapsed = {elapsed}s")
                                    continue
                    except asyncio.TimeoutError:
                        logger.warning(f"Request #{self.request_count}: Poll timeout at {elapsed}s, retrying...")
                        continue
                    except Exception as e:
                        logger.warning(f"Request #{self.request_count}: Poll error at {elapsed}s: {e}, retrying...")
                        continue
                
                logger.error(f"Request #{self.request_count}: Timeout after {elapsed}s")
                return web.json_response({
                    'error': 'Timeout waiting for result'
                }, status=504)
                    
        except Exception as e:
            logger.error(f"Request #{self.request_count}: Unexpected error - {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def proxy_tags(self, request: web.Request) -> web.Response:
        """Proxy /api/tags requests to coordinator"""
        try:
            async with ClientSession() as session:
                url = f"{self.coordinator_url}/api/tags"
                async with session.get(url, timeout=ClientTimeout(total=10)) as resp:
                    result = await resp.json()
                    return web.json_response(result, status=resp.status)
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def get_version(self, request: web.Request) -> web.Response:
        """Return version information (Ollama compatible)"""
        return web.json_response({
            'version': 'distributed-ollama-v1.0.0'
        })
    
    async def health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        try:
            async with ClientSession() as session:
                url = f"{self.coordinator_url}/api/status"
                async with session.get(url, timeout=ClientTimeout(total=60)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        active_workers = data['coordinator']['active_workers']
                        return web.json_response({
                            'status': 'healthy',
                            'coordinator': 'connected',
                            'active_workers': active_workers,
                            'requests_processed': self.request_count
                        })
                    else:
                        return web.json_response({
                            'status': 'degraded',
                            'coordinator': 'error'
                        }, status=503)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return web.json_response({
                'status': 'unhealthy',
                'coordinator': 'unreachable',
                'error': str(e)
            }, status=503)
    
    async def keep_coordinator_alive(self):
        """Ping coordinator every 10 minutes to prevent Render free tier sleep"""
        while True:
            try:
                await asyncio.sleep(600)  # 10 minutes
                async with ClientSession() as session:
                    url = f"{self.coordinator_url}/api/status"
                    async with session.get(url, timeout=ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            logger.debug("Keep-alive ping to coordinator successful")
                        else:
                            logger.warning(f"Keep-alive ping returned HTTP {resp.status}")
            except Exception as e:
                logger.debug(f"Keep-alive ping failed (coordinator may be sleeping): {e}")

    async def start(self):
        """Start the proxy server"""
        app = web.Application()
        
        # Ollama-compatible routes
        app.router.add_post('/api/generate', self.proxy_generate)
        app.router.add_get('/api/tags', self.proxy_tags)
        app.router.add_get('/api/version', self.get_version)
        
        # Additional routes
        app.router.add_get('/health', self.health_check)
        
        # Start keep-alive task to prevent coordinator sleeping
        asyncio.create_task(self.keep_coordinator_alive())
        
        logger.info("=" * 70)
        logger.info("Distributed Ollama Public Proxy")
        logger.info("=" * 70)
        logger.info(f"Proxy server: http://{self.host}:{self.port}")
        logger.info(f"Coordinator: {self.coordinator_url}")
        logger.info("")
        logger.info("Available endpoints:")
        logger.info(f"  - POST /api/generate")
        logger.info(f"  - GET  /api/tags")
        logger.info(f"  - GET  /health")
        logger.info("")
        logger.info("This proxy is Ollama API compatible!")
        logger.info("=" * 70)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        # Keep running
        await asyncio.Event().wait()


async def main():
    import os
    parser = argparse.ArgumentParser(
        description='Distributed Ollama Public Proxy',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This proxy provides a public Ollama-compatible API endpoint that forwards
requests to the distributed coordinator, making the entire cluster accessible
via a single URL.

Examples:
  # Start proxy on default port (11434), talking to the public coordinator
  python proxy.py

  # Start on a different port / point at a different coordinator
  python proxy.py --coordinator http://coordinator.example.com:8080 --port 8080

  # Make it publicly accessible
  python proxy.py --coordinator http://coordinator.example.com:8080 --host 0.0.0.0

After starting, you can use this proxy URL in EditorAI or any Ollama client:
  http://your-server-ip:11434
        """
    )

    parser.add_argument(
        '--coordinator',
        default=os.environ.get('PLATINUM_COORDINATOR',
                               'http://sn-1.vltgg.net:21800'),
        help='Coordinator server URL (default: http://sn-1.vltgg.net:21800, '
             'or $PLATINUM_COORDINATOR)'
    )
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0 for public access)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='Port to bind to (default: 11434, same as Ollama)'
    )
    
    args = parser.parse_args()
    
    # Use PORT env var if available (for platforms like Render)
    port = args.port or int(os.environ.get('PORT', 11434))
    
    proxy = OllamaProxy(
        coordinator_url=args.coordinator,
        host=args.host,
        port=port
    )
    
    await proxy.start()


if __name__ == '__main__':
    asyncio.run(main())
