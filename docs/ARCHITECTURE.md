# Architecture Overview

This document explains how Distributed Ollama works under the hood.

## System Components

```
┌─────────────────────────────────────────────────────────────┐
│                        USER LAYER                            │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   EditorAI   │  │  cURL/API    │  │ Other Clients│      │
│  │    Client    │  │   Clients    │  │              │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
                    HTTP POST /api/generate
                             │
┌────────────────────────────┼─────────────────────────────────┐
│                     PUBLIC PROXY LAYER                        │
├────────────────────────────┼─────────────────────────────────┤
│                            ▼                                  │
│              ┌──────────────────────────┐                    │
│              │   Public Proxy Server    │                    │
│              │   (Port 11434)           │                    │
│              │                          │                    │
│              │  - Ollama API Compatible │                    │
│              │  - Request Forwarding    │                    │
│              │  - Health Checks         │                    │
│              └──────────┬───────────────┘                    │
│                         │                                     │
└─────────────────────────┼─────────────────────────────────────┘
                          │
                 HTTP POST to Coordinator
                          │
┌─────────────────────────┼─────────────────────────────────────┐
│                  COORDINATOR LAYER                            │
├─────────────────────────┼─────────────────────────────────────┤
│                         ▼                                     │
│         ┌───────────────────────────────┐                    │
│         │   Coordinator Server          │                    │
│         │   (Port 8080)                 │                    │
│         │                               │                    │
│         │  Core Functions:              │                    │
│         │  - Worker Registration        │                    │
│         │  - Heartbeat Monitoring       │                    │
│         │  - Load Balancing             │                    │
│         │  - Request Routing            │                    │
│         │                               │                    │
│         │  Worker Selection:            │                    │
│         │  1. Model availability        │                    │
│         │  2. Worker status (idle/busy) │                    │
│         │  3. Available VRAM            │                    │
│         │  4. Current load              │                    │
│         └───────────┬───────────────────┘                    │
│                     │                                         │
└─────────────────────┼─────────────────────────────────────────┘
                      │
          ┌───────────┼───────────┐
          │           │           │
          ▼           ▼           ▼
┌──────────────────────────────────────────────────────────────┐
│                      WORKER LAYER                             │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Worker 1   │  │   Worker 2   │  │   Worker N   │      │
│  │              │  │              │  │              │      │
│  │ RTX 4090     │  │ GTX 1080     │  │ CPU Only     │      │
│  │ 24GB VRAM    │  │ 8GB VRAM     │  │ 0GB VRAM     │      │
│  │              │  │              │  │              │      │
│  │ Models:      │  │ Models:      │  │ Models:      │      │
│  │ - llama2     │  │ - mistral    │  │ - phi        │      │
│  │ - codellama  │  │ - phi        │  │ - tinyllama  │      │
│  │ - mistral    │  │              │  │              │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Local Ollama   │
                    │ (Port 11434)   │
                    └────────────────┘
```

## Data Flow

### 1. Worker Registration

```
Worker                Coordinator
  │                        │
  │─────Register───────────>│
  │  - Worker ID            │
  │  - Resources            │  • Store worker info
  │  - Models               │  • Add to worker pool
  │  - Address:Port         │
  │                        │
  │<─────Response───────────│
  │   worker_id            │
  │                        │
  │────Heartbeat (10s)─────>│
  │  - Status              │  • Update last_seen
  │  - Available resources │  • Update resources
  │                        │
```

### 2. Request Processing

```
Client              Proxy          Coordinator        Worker
  │                   │                 │               │
  │─POST /generate────>│                 │               │
  │  - model          │                 │               │
  │  - prompt         │                 │               │
  │                   │                 │               │
  │                   │─Forward─────────>│               │
  │                   │                 │               │
  │                   │                 │  • Find best  │
  │                   │                 │    worker     │
  │                   │                 │  • Check load │
  │                   │                 │  • Route req  │
  │                   │                 │               │
  │                   │                 │──Forward──────>│
  │                   │                 │               │
  │                   │                 │               │  • Process
  │                   │                 │               │  • Generate
  │                   │                 │<──Response────│
  │                   │<────Response────│               │
  │<──Response────────│                 │               │
  │                   │                 │               │
```

### 3. Worker Selection Algorithm

```python
def find_best_worker(model: str) -> Worker:
    # 1. Filter by model availability
    candidates = [w for w in workers if model in w.models]
    
    # 2. Filter by status
    idle = [w for w in candidates if w.status == IDLE]
    if not idle:
        # Try busy workers with capacity
        idle = [w for w in candidates 
                if w.status == BUSY and w.current_requests < 2]
    
    if not idle:
        return None
    
    # 3. Sort by available VRAM (descending)
    #    and current load (ascending)
    idle.sort(
        key=lambda w: (w.resources.available_vram_gb, -w.current_requests),
        reverse=True
    )
    
    # 4. Return best worker
    return idle[0]
```

## Component Details

### Coordinator (`coordinator/server.py`)

**Responsibilities:**
- Maintain worker registry
- Process heartbeats
- Route inference requests
- Monitor worker health
- Balance load across workers

**Key Data Structures:**
```python
workers: Dict[str, Worker] = {
    "worker-id-1": Worker(
        id="worker-id-1",
        address="192.168.1.100",
        port=11435,
        status=WorkerStatus.IDLE,
        resources=WorkerResources(...),
        models=["llama2", "mistral"],
        last_heartbeat=datetime.now(),
        current_requests=0,
        total_requests=142
    )
}
```

**Endpoints:**
- `POST /api/workers/register` - Worker registration
- `POST /api/workers/heartbeat` - Receive heartbeat
- `POST /api/generate` - Process generation request
- `GET /api/tags` - List available models
- `GET /api/status` - Get system status

### Proxy (`proxy/server.py`)

**Responsibilities:**
- Provide Ollama-compatible API
- Forward requests to coordinator
- Handle errors gracefully
- Provide health checks

**Key Features:**
- Port 11434 (same as Ollama)
- Fully compatible with Ollama clients
- Automatic retry on failure
- Request/response logging

**Endpoints:**
- `POST /api/generate` - Generate text
- `GET /api/tags` - List models
- `GET /api/version` - Get version
- `GET /health` - Health check

### Worker (`worker/client.py`)

**Responsibilities:**
- Connect to local Ollama
- Register with coordinator
- Send periodic heartbeats
- Report system resources

**Key Features:**
- Auto-detect GPU/VRAM
- Monitor resource usage
- Handle multiple models
- Graceful shutdown

**Resource Detection:**
```python
def get_system_resources():
    # RAM
    ram = psutil.virtual_memory()
    
    # VRAM (via nvidia-smi)
    gpu_name, total_vram, free_vram = get_gpu_info()
    
    # Disk
    disk = psutil.disk_usage('/')
    
    # CPU
    cpu_count = psutil.cpu_count()
    
    return SystemResources(...)
```

## Scaling Considerations

### Horizontal Scaling

Add more workers to increase capacity:

```
1 Coordinator
     ↓
  10 Workers × 8GB VRAM = 80GB total VRAM
     ↓
  ~10 concurrent requests
```

Add more coordinators for redundancy:

```
Load Balancer
     ↓
  3 Coordinators
     ↓
  30 Workers
```

### Vertical Scaling

Upgrade coordinator/proxy server:
- More RAM = can handle more workers
- Better CPU = faster routing
- Better network = lower latency

### Performance Optimization

1. **Model Caching**: Workers cache loaded models
2. **Connection Pooling**: Reuse HTTP connections
3. **Async I/O**: Non-blocking operations
4. **Smart Routing**: Prefer idle over busy workers

## Security Model

### Current Implementation (v1.0)

**Trust-based:**
- No authentication
- No encryption (HTTP only)
- Workers trusted implicitly
- Open registration

**Suitable for:**
- Private networks
- Trusted users
- Development/testing
- Small communities

### Recommended Additions for Production

1. **Authentication:**
   ```python
   headers = {"Authorization": f"Bearer {api_key}"}
   ```

2. **TLS/SSL:**
   ```
   https://ollama.example.com
   ```

3. **Rate Limiting:**
   ```python
   @rate_limit(requests=100, period=3600)
   async def generate(request):
       ...
   ```

4. **Worker Verification:**
   ```python
   worker_signature = sign(worker_id, secret_key)
   ```

## Monitoring

### Key Metrics

**Coordinator:**
- Active workers count
- Total requests processed
- Average response time
- Error rate
- Worker uptime

**Worker:**
- VRAM usage
- RAM usage
- Requests processed
- Average processing time
- Model load times

**Proxy:**
- Requests per second
- Latency percentiles (p50, p95, p99)
- Error rate
- Active connections

### Logging

All components log to stdout:

```
2026-02-14 12:00:00 - coordinator - INFO - Registered worker abc123
2026-02-14 12:00:10 - coordinator - INFO - Request completed on worker abc123
2026-02-14 12:00:20 - worker - INFO - Heartbeat sent
```

## Error Handling

### Network Failures

- **Coordinator down**: Proxy returns 503
- **Worker down**: Coordinator marks offline, routes to another
- **Request timeout**: Return 504, worker marked busy

### Resource Exhaustion

- **No workers available**: Return 503 with retry-after
- **VRAM full**: Worker refuses new requests until space available
- **Model not found**: Return 404 with available models list

## Future Enhancements

1. **Model Pre-loading**: Load popular models in advance
2. **Request Queuing**: Queue requests when all workers busy
3. **Streaming Support**: Real-time token streaming
4. **A/B Testing**: Route to different model versions
5. **Cost Tracking**: Track resource usage per user
6. **Auto-scaling**: Automatically request more workers
7. **Multi-region**: Deploy coordinators in multiple regions
8. **Model Sharding**: Split large models across workers

---

This architecture provides a solid foundation for distributed inference while remaining simple and maintainable.
