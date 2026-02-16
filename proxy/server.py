#!/usr/bin/env python3
"""
Public Ollama Proxy
Provides a public URL interface that forwards to the coordinator
This makes the distributed Ollama cluster accessible via a single public endpoint
"""

import asyncio
import logging
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
        """Proxy /api/generate requests to coordinator using queue system"""
        try:
            self.request_count += 1
            data = await request.json()
            
            logger.info(f"Request #{self.request_count}: Generating with model '{data.get('model', 'unknown')}'")
            
            async with ClientSession() as session:
                # Step 1: Queue the request
                url = f"{self.coordinator_url}/api/generate"
                async with session.post(url, json=data, timeout=ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Request #{self.request_count}: Failed to queue - {error_text}")
                        return web.json_response({
                            'error': error_text
                        }, status=resp.status)
                    
                    queue_result = await resp.json()
                    request_id = queue_result.get('request_id')
                    
                    if not request_id:
                        return web.json_response({
                            'error': 'No request_id returned'
                        }, status=500)
                    
                    logger.info(f"Request #{self.request_count}: Queued as {request_id}")
                
                # Step 2: Poll for result
                result_url = f"{self.coordinator_url}/api/result/{request_id}"
                max_wait = 300  # 5 minutes
                poll_interval = 2  # seconds
                elapsed = 0
                
                while elapsed < max_wait:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                    
                    async with session.get(result_url, timeout=ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            result_data = await resp.json()
                            status = result_data.get('status')
                            
                            if status == 'completed':
                                logger.info(f"Request #{self.request_count}: Completed successfully")
                                return web.json_response(result_data.get('result', {}))
                            elif status == 'failed':
                                logger.error(f"Request #{self.request_count}: Failed - {result_data.get('error')}")
                                return web.json_response({
                                    'error': result_data.get('error', 'Unknown error')
                                }, status=500)
                            elif status == 'timeout':
                                logger.error(f"Request #{self.request_count}: Timed out")
                                return web.json_response({
                                    'error': 'Request timed out'
                                }, status=504)
                            else:
                                # Still processing, continue polling
                                logger.debug(f"Request #{self.request_count}: Status = {status}, elapsed = {elapsed}s")
                                continue
                
                # Timeout waiting for result
                logger.error(f"Request #{self.request_count}: Timeout after {elapsed}s")
                return web.json_response({
                    'error': 'Timeout waiting for result'
                }, status=504)
                    
        except asyncio.TimeoutError:
            logger.error(f"Request #{self.request_count}: Timeout")
            return web.json_response({
                'error': 'Request timeout. All workers may be busy.'
            }, status=504)
        except Exception as e:
            logger.error(f"Request #{self.request_count}: Error - {e}")
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
            # Check if coordinator is reachable
            async with ClientSession() as session:
                url = f"{self.coordinator_url}/api/status"
                async with session.get(url, timeout=ClientTimeout(total=5)) as resp:
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
    
    async def start(self):
        """Start the proxy server"""
        app = web.Application()
        
        # Ollama-compatible routes
        app.router.add_post('/api/generate', self.proxy_generate)
        app.router.add_get('/api/tags', self.proxy_tags)
        app.router.add_get('/api/version', self.get_version)
        
        # Additional routes
        app.router.add_get('/health', self.health_check)
        
        logger.info("=" * 70)
        logger.info("Distributed Ollama Public Proxy")
        logger.info("=" * 70)
        logger.info(f"Proxy server: http://{self.host}:{self.port}")
        logger.info(f"Coordinator: {self.coordinator_url}")
        logger.info("")
        logger.info("Available endpoints:")
        logger.info(f"  - POST http://{self.host}:{self.port}/api/generate")
        logger.info(f"  - GET  http://{self.host}:{self.port}/api/tags")
        logger.info(f"  - GET  http://{self.host}:{self.port}/health")
        logger.info("")
        logger.info("This proxy is Ollama API compatible!")
        logger.info("You can use it as a drop-in replacement for http://localhost:11434")
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
  # Start proxy on default port (11434)
  python proxy.py --coordinator http://coordinator.example.com:8080
  
  # Start on a different port
  python proxy.py --coordinator http://coordinator.example.com:8080 --port 8080
  
  # Make it publicly accessible
  python proxy.py --coordinator http://coordinator.example.com:8080 --host 0.0.0.0

After starting, you can use this proxy URL in EditorAI or any Ollama client:
  http://your-server-ip:11434
        """
    )
    
    parser.add_argument(
        '--coordinator',
        required=True,
        help='Coordinator server URL (e.g., http://coordinator.example.com:8080)'
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
