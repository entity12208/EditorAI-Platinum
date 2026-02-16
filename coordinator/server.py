#!/usr/bin/env python3
"""
Distributed Ollama Coordinator Server
Manages worker nodes and routes inference requests to available workers
Uses a queue-based architecture so workers can operate behind NAT/firewalls
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from aiohttp import web
import uuid

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    models: List[str]  # List of models available on this worker
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


class CoordinatorServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.workers: Dict[str, Worker] = {}
        self.request_queue: Dict[str, QueuedRequest] = {}  # request_id -> QueuedRequest
        self.heartbeat_timeout = 30  # seconds
        self.request_timeout = 300  # 5 minutes
        
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
            
            logger.info(f"Registered worker {worker_id} at {address}:{port}")
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
            
            # Update resources if provided
            if 'resources' in data:
                res = data['resources']
                worker.resources.available_ram_gb = res.get('available_ram_gb', worker.resources.available_ram_gb)
                worker.resources.available_vram_gb = res.get('available_vram_gb', worker.resources.available_vram_gb)
                worker.resources.available_disk_gb = res.get('available_disk_gb', worker.resources.available_disk_gb)
            
            # Update status if provided
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
    
    async def queue_request(self, request: web.Request) -> web.Response:
        """Queue a generation request for workers to pick up"""
        try:
            data = await request.json()
            model = data.get('model')
            
            if not model:
                return web.json_response({
                    'error': 'Model not specified'
                }, status=400)
            
            # Check if any worker has this model
            available = any(
                model in w.models and w.status != WorkerStatus.OFFLINE 
                for w in self.workers.values()
            )
            
            if not available:
                return web.json_response({
                    'error': f'No workers available for model {model}'
                }, status=503)
            
            # Create queued request
            request_id = str(uuid.uuid4())
            queued_req = QueuedRequest(
                request_id=request_id,
                model=model,
                prompt=data.get('prompt', ''),
                options=data.get('options', {}),
                status=RequestStatus.PENDING,
                created_at=datetime.now()
            )
            
            self.request_queue[request_id] = queued_req
            
            logger.info(f"Queued request {request_id} for model {model}")
            
            return web.json_response({
                'request_id': request_id,
                'status': 'queued'
            })
            
        except Exception as e:
            logger.error(f"Error queuing request: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def get_work(self, request: web.Request) -> web.Response:
        """Worker polls for available work"""
        try:
            worker_id = request.query.get('worker_id')
            
            if not worker_id or worker_id not in self.workers:
                return web.json_response({
                    'error': 'Invalid worker_id'
                }, status=400)
            
            worker = self.workers[worker_id]
            
            # Find pending request that matches worker's models
            for req_id, req in self.request_queue.items():
                if req.status == RequestStatus.PENDING and req.model in worker.models:
                    # Assign to this worker
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
            
            # No work available
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
                req.status = RequestStatus.FAILED
                req.error = data['error']
                logger.error(f"Request {request_id} failed: {data['error']}")
            else:
                req.status = RequestStatus.COMPLETED
                req.result = data.get('result', {})
                logger.info(f"Request {request_id} completed successfully")
            
            req.completed_at = datetime.now()
            
            # Update worker status
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
                # Still pending or processing
                return web.json_response({
                    'status': req.status.value
                })
                
        except Exception as e:
            logger.error(f"Error getting result: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
        
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
            
            logger.info(f"Registered worker {worker_id} at {address}:{port}")
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
            
            # Update resources if provided
            if 'resources' in data:
                res = data['resources']
                worker.resources.available_ram_gb = res.get('available_ram_gb', worker.resources.available_ram_gb)
                worker.resources.available_vram_gb = res.get('available_vram_gb', worker.resources.available_vram_gb)
                worker.resources.available_disk_gb = res.get('available_disk_gb', worker.resources.available_disk_gb)
            
            # Update status if provided
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
    
    
    async def list_models(self, request: web.Request) -> web.Response:
        """List all available models across all workers"""
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
    
    async def get_status(self, request: web.Request) -> web.Response:
        """Get coordinator status and worker information"""
        try:
            workers_info = []
            
            for worker in self.workers.values():
                workers_info.append({
                    'id': worker.id,
                    'address': f"{worker.address}:{worker.port}",
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
        """Remove workers that haven't sent heartbeat in a while"""
        while True:
            try:
                await asyncio.sleep(10)
                
                now = datetime.now()
                
                for worker_id, worker in self.workers.items():
                    time_since_heartbeat = (now - worker.last_heartbeat).total_seconds()
                    
                    if time_since_heartbeat > self.heartbeat_timeout:
                        if worker.status != WorkerStatus.OFFLINE:
                            worker.status = WorkerStatus.OFFLINE
                            logger.warning(f"Worker {worker_id} marked as OFFLINE (no heartbeat for {time_since_heartbeat:.0f}s)")
                
                # Remove offline workers after 5 minutes
                to_remove = []
                for worker_id, worker in self.workers.items():
                    if worker.status == WorkerStatus.OFFLINE:
                        time_offline = (now - worker.last_heartbeat).total_seconds()
                        if time_offline > 300:  # 5 minutes
                            to_remove.append(worker_id)
                
                for worker_id in to_remove:
                    del self.workers[worker_id]
                    logger.info(f"Removed worker {worker_id}")
                            
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
    
    async def cleanup_old_requests(self):
        """Remove completed/failed requests older than 10 minutes"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                now = datetime.now()
                to_remove = []
                
                for req_id, req in self.request_queue.items():
                    # Timeout processing requests after 5 minutes
                    if req.status == RequestStatus.PROCESSING:
                        age = (now - req.created_at).total_seconds()
                        if age > self.request_timeout:
                            req.status = RequestStatus.TIMEOUT
                            req.error = "Request timed out"
                            logger.warning(f"Request {req_id} timed out")
                            
                            # Free up worker
                            if req.assigned_worker and req.assigned_worker in self.workers:
                                worker = self.workers[req.assigned_worker]
                                worker.current_requests = max(0, worker.current_requests - 1)
                                if worker.current_requests == 0:
                                    worker.status = WorkerStatus.IDLE
                    
                    # Remove old completed/failed requests
                    if req.status in [RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.TIMEOUT]:
                        if req.completed_at:
                            age = (now - req.completed_at).total_seconds()
                            if age > 600:  # 10 minutes
                                to_remove.append(req_id)
                
                for req_id in to_remove:
                    del self.request_queue[req_id]
                    logger.debug(f"Removed old request {req_id}")
                    
            except Exception as e:
                logger.error(f"Error in request cleanup task: {e}")
    
    async def start(self):
        """Start the coordinator server"""
        app = web.Application()
        
        # Routes
        app.router.add_post('/api/workers/register', self.register_worker)
        app.router.add_post('/api/workers/heartbeat', self.heartbeat)
        app.router.add_post('/api/generate', self.queue_request)
        app.router.add_get('/api/work', self.get_work)
        app.router.add_post('/api/result/{request_id}', self.submit_result)
        app.router.add_get('/api/result/{request_id}', self.get_result)
        app.router.add_get('/api/tags', self.list_models)
        app.router.add_get('/api/status', self.get_status)
        
        # Start cleanup tasks
        asyncio.create_task(self.cleanup_stale_workers())
        asyncio.create_task(self.cleanup_old_requests())
        
        logger.info(f"Starting coordinator server on {self.host}:{self.port}")
        logger.info("Available endpoints:")
        logger.info(f"  - POST /api/workers/register - Register a new worker")
        logger.info(f"  - POST /api/workers/heartbeat - Worker heartbeat")
        logger.info(f"  - POST /api/generate - Queue generation request")
        logger.info(f"  - GET /api/work - Worker polls for work")
        logger.info(f"  - POST /api/result/{{id}} - Submit result")
        logger.info(f"  - GET /api/result/{{id}} - Get result status")
        logger.info(f"  - GET /api/tags - List available models")
        logger.info(f"  - GET /api/status - Get server status")
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        # Keep running
        await asyncio.Event().wait()


if __name__ == '__main__':
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description='Distributed Ollama Coordinator Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    
    args = parser.parse_args()
    
    # Use PORT env var if available (for platforms like Render)
    port = args.port or int(os.environ.get('PORT', 8080))
    
    coordinator = CoordinatorServer(host=args.host, port=port)
    asyncio.run(coordinator.start())
        """Proxy Ollama API requests to available workers"""
        try:
            # Parse the request
            data = await request.json()
            model = data.get('model')
            
            if not model:
                return web.json_response({
                    'error': 'Model not specified'
                }, status=400)
            
            # Find the best available worker for this model
            worker = self._find_best_worker(model)
            
            if not worker:
                return web.json_response({
                    'error': f'No available workers for model {model}. Please wait or try again later.'
                }, status=503)
            
            # Forward request to worker
            worker.status = WorkerStatus.BUSY
            worker.current_requests += 1
            
            try:
                url = f"http://{worker.address}:{worker.port}/api/generate"
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                        result = await resp.json()
                        
                        worker.current_requests -= 1
                        worker.total_requests += 1
                        
                        if worker.current_requests == 0:
                            worker.status = WorkerStatus.IDLE
                        
                        logger.info(f"Request completed on worker {worker.id} for model {model}")
                        
                        return web.json_response(result)
                        
            except asyncio.TimeoutError:
                worker.current_requests -= 1
                worker.status = WorkerStatus.IDLE
                logger.error(f"Request timeout on worker {worker.id}")
                return web.json_response({
                    'error': 'Request timeout. Please try again.'
                }, status=504)
                
            except Exception as e:
                worker.current_requests -= 1
                worker.status = WorkerStatus.IDLE
                logger.error(f"Error forwarding request to worker: {e}")
                return web.json_response({
                    'error': f'Worker error: {str(e)}'
                }, status=502)
                
        except Exception as e:
            logger.error(f"Error in ollama_proxy: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    async def list_models(self, request: web.Request) -> web.Response:
        """List all available models across all workers"""
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
    
    async def get_status(self, request: web.Request) -> web.Response:
        """Get coordinator status and worker information"""
        try:
            workers_info = []
            
            for worker in self.workers.values():
                workers_info.append({
                    'id': worker.id,
                    'address': f"{worker.address}:{worker.port}",
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
                    'active_workers': len([w for w in self.workers.values() if w.status != WorkerStatus.OFFLINE])
                },
                'workers': workers_info
            })
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return web.json_response({
                'error': str(e)
            }, status=500)
    
    def _find_best_worker(self, model: str) -> Optional[Worker]:
        """Find the best available worker for a given model"""
        available_workers = [
            w for w in self.workers.values()
            if w.status == WorkerStatus.IDLE and model in w.models
        ]
        
        if not available_workers:
            # Try to find a busy but not overloaded worker
            available_workers = [
                w for w in self.workers.values()
                if w.status == WorkerStatus.BUSY and model in w.models and w.current_requests < 2
            ]
        
        if not available_workers:
            return None
        
        # Sort by available VRAM (more VRAM = better)
        available_workers.sort(
            key=lambda w: (w.resources.available_vram_gb, -w.current_requests),
            reverse=True
        )
        
        return available_workers[0]
    
    async def cleanup_stale_workers(self):
        """Remove workers that haven't sent heartbeat in a while"""
        while True:
            try:
                await asyncio.sleep(10)
                
                now = datetime.now()
                stale_workers = []
                
                for worker_id, worker in self.workers.items():
                    time_since_heartbeat = (now - worker.last_heartbeat).total_seconds()
                    
                    if time_since_heartbeat > self.heartbeat_timeout:
                        worker.status = WorkerStatus.OFFLINE
                        logger.warning(f"Worker {worker_id} marked as OFFLINE (no heartbeat for {time_since_heartbeat:.0f}s)")
                        stale_workers.append(worker_id)
                
                # Remove offline workers after 5 minutes
                for worker_id in list(self.workers.keys()):
                    worker = self.workers[worker_id]
                    if worker.status == WorkerStatus.OFFLINE:
                        time_offline = (now - worker.last_heartbeat).total_seconds()
                        if time_offline > 300:  # 5 minutes
                            del self.workers[worker_id]
                            logger.info(f"Removed worker {worker_id} (offline for {time_offline:.0f}s)")
                            
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
    
    async def start(self):
        """Start the coordinator server"""
        app = web.Application()
        
        # Routes
        app.router.add_post('/api/workers/register', self.register_worker)
        app.router.add_post('/api/workers/heartbeat', self.heartbeat)
        app.router.add_post('/api/generate', self.ollama_proxy)
        app.router.add_get('/api/tags', self.list_models)
        app.router.add_get('/api/status', self.get_status)
        
        # Start cleanup task
        asyncio.create_task(self.cleanup_stale_workers())
        
        logger.info(f"Starting coordinator server on {self.host}:{self.port}")
        logger.info("Available endpoints:")
        logger.info(f"  - POST /api/workers/register - Register a new worker")
        logger.info(f"  - POST /api/workers/heartbeat - Worker heartbeat")
        logger.info(f"  - POST /api/generate - Generate text (Ollama compatible)")
        logger.info(f"  - GET /api/tags - List available models")
        logger.info(f"  - GET /api/status - Get server status")
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        # Keep running
        await asyncio.Event().wait()


if __name__ == '__main__':
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description='Distributed Ollama Coordinator Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    
    args = parser.parse_args()
    
    # Use PORT env var if available (for platforms like Render)
    port = args.port or int(os.environ.get('PORT', 8080))
    
    coordinator = CoordinatorServer(host=args.host, port=port)
    asyncio.run(coordinator.start())
