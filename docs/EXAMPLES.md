# Example Configurations

This file contains example configurations for various deployment scenarios.

## Scenario 1: Small Community Server (5-10 users)

### Setup
- 1 VPS (coordinator + proxy)
- 3-5 community-donated workers

### Coordinator Config
```bash
python coordinator/server.py \
  --host 0.0.0.0 \
  --port 8080
```

### Proxy Config
```bash
python proxy/server.py \
  --coordinator http://localhost:8080 \
  --host 0.0.0.0 \
  --port 11434
```

### Worker Config
```bash
# Each donor runs:
python worker/client.py \
  --coordinator http://your-vps-ip:8080 \
  --ollama-host localhost \
  --ollama-port 11434
```

### Expected Performance
- 3-5 concurrent requests
- ~20-30 second generation time
- Models: llama2, mistral, phi

---

## Scenario 2: Large Public Service (100+ users)

### Setup
- 1 Load Balancer
- 3 VPS (coordinator cluster)
- 1 Proxy server
- 20+ community workers

### Load Balancer (nginx)
```nginx
upstream coordinators {
    server coordinator1.example.com:8080;
    server coordinator2.example.com:8080;
    server coordinator3.example.com:8080;
}

server {
    listen 8080;
    location / {
        proxy_pass http://coordinators;
    }
}
```

### Coordinator Config (each instance)
```bash
python coordinator/server.py \
  --host 0.0.0.0 \
  --port 8080
```

### Proxy Config
```bash
python proxy/server.py \
  --coordinator http://loadbalancer.example.com:8080 \
  --host 0.0.0.0 \
  --port 11434
```

### Expected Performance
- 20+ concurrent requests
- ~5-10 second generation time
- Models: Multiple options available

---

## Scenario 3: Private Organization

### Setup
- On-premises coordinator
- Internal network workers
- VPN access for remote workers

### Coordinator Config
```bash
python coordinator/server.py \
  --host 0.0.0.0 \
  --port 8080
```

### Internal Worker Config
```bash
python worker/client.py \
  --coordinator http://coordinator.internal:8080 \
  --ollama-host localhost \
  --ollama-port 11434
```

### Remote Worker Config (via VPN)
```bash
python worker/client.py \
  --coordinator http://coordinator.internal:8080 \
  --ollama-host localhost \
  --ollama-port 11434
```

---

## Scenario 4: Multiple GPU Worker

### Setup
- One machine with multiple GPUs
- Run multiple Ollama instances
- Run multiple workers

### GPU 0 (Ollama on port 11434)
```bash
CUDA_VISIBLE_DEVICES=0 ollama serve &
python worker/client.py \
  --coordinator http://coordinator:8080 \
  --ollama-port 11434 \
  --worker-id machine1-gpu0
```

### GPU 1 (Ollama on port 11435)
```bash
CUDA_VISIBLE_DEVICES=1 ollama serve --port 11435 &
python worker/client.py \
  --coordinator http://coordinator:8080 \
  --ollama-port 11435 \
  --worker-id machine1-gpu1
```

### GPU 2 (Ollama on port 11436)
```bash
CUDA_VISIBLE_DEVICES=2 ollama serve --port 11436 &
python worker/client.py \
  --coordinator http://coordinator:8080 \
  --ollama-port 11436 \
  --worker-id machine1-gpu2
```

---

## Scenario 5: Docker Swarm Deployment

### docker-compose.yml for Swarm
```yaml
version: '3.8'

services:
  coordinator:
    image: distributed-ollama:latest
    command: python coordinator/server.py --host 0.0.0.0 --port 8080
    ports:
      - "8080:8080"
    deploy:
      replicas: 3
      restart_policy:
        condition: on-failure
    networks:
      - ollama-net

  proxy:
    image: distributed-ollama:latest
    command: python proxy/server.py --coordinator http://coordinator:8080 --host 0.0.0.0 --port 11434
    ports:
      - "11434:11434"
    depends_on:
      - coordinator
    deploy:
      replicas: 2
      restart_policy:
        condition: on-failure
    networks:
      - ollama-net

networks:
  ollama-net:
    driver: overlay
```

Deploy:
```bash
docker stack deploy -c docker-compose.yml ollama
```

---

## Scenario 6: Development/Testing

### Setup
- All components on localhost
- Single worker for testing

### Start Everything
```bash
# Terminal 1: Coordinator
python coordinator/server.py --host 127.0.0.1 --port 8080

# Terminal 2: Proxy
python proxy/server.py --coordinator http://127.0.0.1:8080 --port 11434

# Terminal 3: Ollama
ollama serve

# Terminal 4: Worker
python worker/client.py --coordinator http://127.0.0.1:8080

# Terminal 5: Test
curl http://127.0.0.1:11434/health
```

---

## Environment Variables

### Coordinator
```bash
export COORDINATOR_HOST=0.0.0.0
export COORDINATOR_PORT=8080
export HEARTBEAT_TIMEOUT=30
```

### Proxy
```bash
export COORDINATOR_URL=http://coordinator:8080
export PROXY_HOST=0.0.0.0
export PROXY_PORT=11434
```

### Worker
```bash
export COORDINATOR_URL=http://coordinator:8080
export OLLAMA_HOST=localhost
export OLLAMA_PORT=11434
export WORKER_ID=my-worker
```

---

## Model Recommendations by Use Case

### For EditorAI (Game Level Generation)
```bash
# Best quality
ollama pull llama2:13b

# Good balance
ollama pull llama2:7b
ollama pull mistral:7b

# Fast generation
ollama pull phi:2.7b
```

### For Code Generation
```bash
ollama pull codellama:13b
ollama pull codellama:7b
ollama pull phind-codellama:34b
```

### For Chat/General Use
```bash
ollama pull llama2:70b  # Needs 64GB+ VRAM
ollama pull mistral:7b
ollama pull llama2:13b
```

### For Low-End Hardware
```bash
ollama pull phi:2.7b
ollama pull tinyllama:1.1b
```

---

## Performance Tuning

### Coordinator
```python
coordinator = CoordinatorServer(
    host="0.0.0.0",
    port=8080
)
coordinator.heartbeat_timeout = 30  # Faster failover
```

### Worker
```python
# Increase heartbeat frequency for faster failover
HEARTBEAT_INTERVAL = 5  # seconds
```

### Ollama
```bash
# Increase context window
ollama run llama2 --num-ctx 4096

# Increase parallelism
ollama run llama2 --num-parallel 4
```

---

## Monitoring Setup

### Prometheus Exporter (example)
```python
from prometheus_client import Counter, Gauge

requests_total = Counter('ollama_requests_total', 'Total requests')
active_workers = Gauge('ollama_active_workers', 'Active workers')
```

### Grafana Dashboard Queries
```
# Active workers over time
rate(ollama_active_workers[5m])

# Request rate
rate(ollama_requests_total[5m])

# Error rate
rate(ollama_errors_total[5m]) / rate(ollama_requests_total[5m])
```

---

## Resource Planning

### Workers per GPU VRAM

| VRAM | Small Model (phi) | Medium Model (llama2:7b) | Large Model (llama2:13b) |
|------|-------------------|--------------------------|--------------------------|
| 4GB  | 1-2 workers       | 0                        | 0                        |
| 8GB  | 2-3 workers       | 1 worker                 | 0                        |
| 12GB | 3-4 workers       | 1-2 workers              | 0                        |
| 16GB | 4-5 workers       | 2 workers                | 1 worker                 |
| 24GB | 6-8 workers       | 3 workers                | 1-2 workers              |

### VPS Requirements

| Users | vCPUs | RAM  | Storage | Network |
|-------|-------|------|---------|---------|
| 1-10  | 1     | 512MB| 10GB    | 1TB     |
| 10-50 | 2     | 2GB  | 20GB    | 2TB     |
| 50-100| 4     | 4GB  | 40GB    | 5TB     |
| 100+  | 8+    | 8GB+ | 100GB+  | 10TB+   |

---

## Backup and Recovery

### Backup Script
```bash
#!/bin/bash
# Backup coordinator state
curl http://localhost:8080/api/status > backup-$(date +%Y%m%d).json
```

### Recovery
```bash
# Restart services
sudo systemctl restart ollama-coordinator
sudo systemctl restart ollama-proxy

# Verify
curl http://localhost:11434/health
```

---

These configurations should cover most deployment scenarios. Adjust as needed for your specific use case!
