#!/usr/bin/env python3
"""
Distributed Ollama Worker Client
Runs on contributor machines to donate compute resources
"""

import asyncio
import json
import logging
import platform
import subprocess
import sys
import time
from typing import List, Dict, Optional
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
    """System resource information"""
    total_ram_gb: float
    available_ram_gb: float
    total_vram_gb: float
    available_vram_gb: float
    total_disk_gb: float
    available_disk_gb: float
    cpu_count: int
    gpu_name: Optional[str] = None


class OllamaWorker:
    def __init__(
        self,
        coordinator_url: str,
        ollama_host: str = "localhost",
        ollama_port: int = 11434,
        worker_port: int = 11435,
        worker_id: Optional[str] = None
    ):
        self.coordinator_url = coordinator_url.rstrip('/')
        self.ollama_host = ollama_host
        self.ollama_port = ollama_port
        self.worker_port = worker_port
        self.worker_id = worker_id or str(uuid.uuid4())
        self.is_running = False
        self.ollama_url = f"http://{ollama_host}:{ollama_port}"
        
    def get_gpu_info(self) -> tuple[Optional[str], float, float]:
        """Get GPU information using nvidia-smi if available"""
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total,memory.free', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if lines:
                    # Use first GPU
                    parts = lines[0].split(',')
                    gpu_name = parts[0].strip()
                    total_vram = float(parts[1].strip()) / 1024  # Convert MB to GB
                    free_vram = float(parts[2].strip()) / 1024
                    return gpu_name, total_vram, free_vram
                    
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"Could not get GPU info: {e}")
        
        return None, 0.0, 0.0
    
    def get_system_resources(self) -> SystemResources:
        """Get current system resource information"""
        # RAM
        ram = psutil.virtual_memory()
        total_ram_gb = ram.total / (1024**3)
        available_ram_gb = ram.available / (1024**3)
        
        # Disk
        disk = psutil.disk_usage('/')
        total_disk_gb = disk.total / (1024**3)
        available_disk_gb = disk.free / (1024**3)
        
        # CPU
        cpu_count = psutil.cpu_count(logical=False) or 1
        
        # GPU/VRAM
        gpu_name, total_vram_gb, available_vram_gb = self.get_gpu_info()
        
        return SystemResources(
            total_ram_gb=total_ram_gb,
            available_ram_gb=available_ram_gb,
            total_vram_gb=total_vram_gb,
            available_vram_gb=available_vram_gb,
            total_disk_gb=total_disk_gb,
            available_disk_gb=available_disk_gb,
            cpu_count=cpu_count,
            gpu_name=gpu_name
        )
    
    async def get_ollama_models(self) -> List[str]:
        """Get list of models available in local Ollama"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_url}/api/tags", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [model['name'] for model in data.get('models', [])]
                        return models
                    else:
                        logger.error(f"Failed to get models from Ollama: HTTP {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"Error connecting to Ollama: {e}")
            logger.error(f"Make sure Ollama is running on {self.ollama_url}")
            return []
    
    async def register_with_coordinator(self) -> bool:
        """Register this worker with the coordinator"""
        try:
            resources = self.get_system_resources()
            models = await self.get_ollama_models()
            
            if not models:
                logger.error("No models found in Ollama. Please install at least one model.")
                logger.info("You can install models with: ollama pull <model-name>")
                logger.info("Popular models: llama2, mistral, codellama, phi")
                return False
            
            # Get public IP for registration
            public_ip = await self._get_public_ip()
            
            registration_data = {
                'worker_id': self.worker_id,
                'address': public_ip or 'localhost',
                'port': self.worker_port,
                'resources': {
                    'total_ram_gb': resources.total_ram_gb,
                    'available_ram_gb': resources.available_ram_gb,
                    'total_vram_gb': resources.total_vram_gb,
                    'available_vram_gb': resources.available_vram_gb,
                    'total_disk_gb': resources.total_disk_gb,
                    'available_disk_gb': resources.available_disk_gb,
                    'cpu_count': resources.cpu_count,
                    'gpu_name': resources.gpu_name
                },
                'models': models
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.coordinator_url}/api/workers/register"
                async with session.post(url, json=registration_data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        logger.info(f"Successfully registered with coordinator")
                        logger.info(f"Worker ID: {self.worker_id}")
                        logger.info(f"Models available: {', '.join(models[:5])}{'...' if len(models) > 5 else ''}")
                        logger.info(f"Resources:")
                        logger.info(f"  - CPU: {resources.cpu_count} cores")
                        logger.info(f"  - RAM: {resources.available_ram_gb:.1f}/{resources.total_ram_gb:.1f} GB")
                        if resources.total_vram_gb > 0:
                            logger.info(f"  - VRAM: {resources.available_vram_gb:.1f}/{resources.total_vram_gb:.1f} GB ({resources.gpu_name})")
                        logger.info(f"  - Disk: {resources.available_disk_gb:.1f}/{resources.total_disk_gb:.1f} GB")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Failed to register: HTTP {resp.status} - {error}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error registering with coordinator: {e}")
            return False
    
    async def _get_public_ip(self) -> Optional[str]:
        """Get public IP address"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.ipify.org?format=json', timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('ip')
        except Exception as e:
            logger.debug(f"Could not get public IP: {e}")
        return None
    
    async def send_heartbeat(self):
        """Send periodic heartbeat to coordinator"""
        while self.is_running:
            try:
                resources = self.get_system_resources()
                
                heartbeat_data = {
                    'worker_id': self.worker_id,
                    'status': 'idle',  # Could be updated based on actual load
                    'resources': {
                        'available_ram_gb': resources.available_ram_gb,
                        'available_vram_gb': resources.available_vram_gb,
                        'available_disk_gb': resources.available_disk_gb
                    }
                }
                
                async with aiohttp.ClientSession() as session:
                    url = f"{self.coordinator_url}/api/workers/heartbeat"
                    async with session.post(url, json=heartbeat_data, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status != 200:
                            logger.warning(f"Heartbeat failed: HTTP {resp.status}")
                            
            except Exception as e:
                logger.error(f"Error sending heartbeat: {e}")
            
            await asyncio.sleep(10)  # Send heartbeat every 10 seconds
    
    async def check_ollama_running(self) -> bool:
        """Check if Ollama is running"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False
    
    async def start(self):
        """Start the worker"""
        logger.info("=" * 60)
        logger.info("Distributed Ollama Worker")
        logger.info("=" * 60)
        logger.info(f"Worker ID: {self.worker_id}")
        logger.info(f"Coordinator: {self.coordinator_url}")
        logger.info(f"Local Ollama: {self.ollama_url}")
        logger.info("=" * 60)
        
        # Check if Ollama is running
        logger.info("Checking if Ollama is running...")
        if not await self.check_ollama_running():
            logger.error("Ollama is not running!")
            logger.error(f"Please start Ollama and ensure it's accessible at {self.ollama_url}")
            logger.error("You can start Ollama with: ollama serve")
            return
        
        logger.info("✓ Ollama is running")
        
        # Register with coordinator
        logger.info("Registering with coordinator...")
        if not await self.register_with_coordinator():
            logger.error("Failed to register with coordinator. Exiting.")
            return
        
        self.is_running = True
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self.send_heartbeat())
        
        logger.info("=" * 60)
        logger.info("Worker is now active and accepting requests!")
        logger.info("Your resources are being shared with the network.")
        logger.info("Press Ctrl+C to stop donating resources.")
        logger.info("=" * 60)
        
        try:
            # Keep running
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("\nShutting down worker...")
            self.is_running = False
            heartbeat_task.cancel()
            logger.info("Worker stopped. Thank you for contributing!")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Distributed Ollama Worker - Donate your compute resources',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Connect to the public coordinator (default)
  python worker.py
  
  # Connect to a custom coordinator
  python worker.py --coordinator http://coordinator.example.com:8080
  
  # Use a custom Ollama port
  python worker.py --ollama-port 11434
  
  # Specify a custom worker ID (useful for multiple GPUs)
  python worker.py --worker-id my-gpu-1
        """
    )
    
    parser.add_argument(
        '--coordinator',
        default='https://ollama-coordinator.onrender.com',
        help='Coordinator server URL (default: https://ollama-coordinator.onrender.com)'
    )
    parser.add_argument(
        '--ollama-host',
        default='localhost',
        help='Ollama host (default: localhost)'
    )
    parser.add_argument(
        '--ollama-port',
        type=int,
        default=11434,
        help='Ollama port (default: 11434)'
    )
    parser.add_argument(
        '--worker-port',
        type=int,
        default=11435,
        help='Port for this worker to receive requests (default: 11435)'
    )
    parser.add_argument(
        '--worker-id',
        help='Custom worker ID (default: auto-generated UUID)'
    )
    
    args = parser.parse_args()
    
    worker = OllamaWorker(
        coordinator_url=args.coordinator,
        ollama_host=args.ollama_host,
        ollama_port=args.ollama_port,
        worker_port=args.worker_port,
        worker_id=args.worker_id
    )
    
    await worker.start()


if __name__ == '__main__':
    asyncio.run(main())
