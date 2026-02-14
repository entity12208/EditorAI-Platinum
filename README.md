# Distributed Ollama Network

A distributed computing system that allows users to donate their GPU/CPU resources to run Ollama models faster. This system pools compute resources from multiple contributors to provide free, fast inference for projects like EditorAI.

## 🚀 Key Features

- **Resource Pooling**: Combine VRAM, RAM, and compute from multiple donor machines
- **Ollama API Compatible**: Drop-in replacement for `http://localhost:11434`
- **Smart Load Balancing**: Automatically routes requests to the best available worker
- **Real-time Monitoring**: Track worker status, resource usage, and request metrics
- **Easy Setup**: Simple Python scripts with minimal configuration
- **Zero Cost**: Completely free to use for end users

## 📐 Architecture

```
┌─────────────────┐
│   EditorAI      │  (or any Ollama client)
│   User          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Public Proxy   │  http://your-server.com:11434
│  (Port Forward) │  Ollama-compatible API endpoint
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Coordinator    │  Manages workers and routes requests
│  Server         │
└────────┬────────┘
         │
    ┌────┴────┬────────┬────────┐
    ▼         ▼        ▼        ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│Worker 1│ │Worker 2│ │Worker 3│ │Worker N│
│ RTX    │ │ GTX    │ │ CPU    │ │ ...    │
│ 4090   │ │ 1080   │ │ Only   │ │        │
└────────┘ └────────┘ └────────┘ └────────┘
   Donors running Ollama locally
```

## 🔧 Installation

### Prerequisites

- Python 3.8 or higher
- For workers: [Ollama](https://ollama.ai/) installed and running

### Install Dependencies

```bash
pip install -r requirements.txt
```

## 🎯 Quick Start

### 1. Start the Coordinator Server

The coordinator manages all workers and routes requests.

```bash
python coordinator/server.py --host 0.0.0.0 --port 8080
```

**Outputs:**
- Manages worker registration and heartbeats
- Routes inference requests to available workers
- API endpoint: `http://localhost:8080`

### 2. Start the Public Proxy (Optional but Recommended)

The proxy provides a public Ollama-compatible endpoint.

```bash
python proxy/server.py \
  --coordinator http://localhost:8080 \
  --host 0.0.0.0 \
  --port 11434
```

**Outputs:**
- Public API: `http://your-server-ip:11434`
- Compatible with standard Ollama clients
- Same as Ollama's default port (11434)

### 3. Run a Worker (Donate Your Resources!)

On any machine with Ollama installed:

```bash
# Make sure Ollama is running first
ollama serve

# In another terminal, start the worker
python worker/client.py \
  --coordinator http://coordinator-server.com:8080
```

**The worker will:**
- Detect your GPU/CPU/RAM automatically
- Register available Ollama models
- Send heartbeats every 10 seconds
- Accept and process requests from the coordinator

## 📊 Usage Examples

### For EditorAI Users

Simply change the Ollama URL in EditorAI settings to:

```
http://your-distributed-ollama-server.com:11434
```

Instead of:

```
http://localhost:11434
```

That's it! EditorAI will now use the distributed network for faster generation.

### Testing with cURL

```bash
# Generate text
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "prompt": "Create a level with platforms",
    "stream": false
  }'

# List available models
curl http://localhost:11434/api/tags

# Check system health
curl http://localhost:11434/health
```

### Using with Python

```python
import aiohttp
import asyncio

async def generate():
    async with aiohttp.ClientSession() as session:
        url = "http://localhost:11434/api/generate"
        data = {
            "model": "llama2",
            "prompt": "Hello, world!",
            "stream": False
        }
        async with session.post(url, json=data) as resp:
            result = await resp.json()
            print(result['response'])

asyncio.run(generate())
```

## 🖥️ Worker Requirements

To donate your resources, you need:

1. **Ollama Installed**:
   ```bash
   # Install Ollama from https://ollama.ai/
   ollama serve
   ```

2. **At least one model downloaded**:
   ```bash
   # Download popular models
   ollama pull llama2
   ollama pull mistral
   ollama pull codellama
   ```

3. **Run the worker**:
   ```bash
   python worker/client.py --coordinator http://coordinator-url:8080
   ```

### What Gets Shared?

- ✅ GPU/VRAM for model inference
- ✅ CPU for processing
- ✅ RAM for model loading
- ✅ Disk space for models
- ❌ Your personal data (never accessed)
- ❌ Internet bandwidth (minimal, only for requests)

## 📈 Monitoring

### Check Coordinator Status

```bash
curl http://coordinator-server.com:8080/api/status
```

**Sample output:**
```json
{
  "coordinator": {
    "status": "running",
    "workers": 5,
    "active_workers": 4
  },
  "workers": [
    {
      "id": "abc123",
      "address": "192.168.1.100:11435",
      "status": "idle",
      "vram": "22.5/24.0 GB",
      "gpu": "NVIDIA RTX 4090",
      "models": 8,
      "requests": "0 active / 142 total"
    }
  ]
}
```

### View Proxy Health

```bash
curl http://localhost:11434/health
```

## 🔒 Security Considerations

### Current Implementation (v1.0)

This is a **proof-of-concept** designed for trusted networks. Security features to add before production:

**Recommended additions:**
- Authentication/API keys for workers and clients
- TLS/SSL encryption for all communication
- Request validation and sanitization
- Rate limiting per client
- Worker verification/reputation system
- Sandboxed execution environment

### Deployment Recommendations

1. **Run on a VPS**: Deploy the coordinator and proxy on a cloud server
2. **Use a reverse proxy**: Put nginx/Caddy in front for TLS
3. **Firewall rules**: Restrict access to known IPs if possible
4. **Monitor resources**: Set up alerts for unusual activity

## 🐳 Docker Deployment (Optional)

### Coordinator + Proxy

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY coordinator/ coordinator/
COPY proxy/ proxy/

# Expose ports
EXPOSE 8080 11434

CMD ["python", "coordinator/server.py"]
```

```bash
# Build
docker build -t distributed-ollama .

# Run coordinator
docker run -d -p 8080:8080 distributed-ollama python coordinator/server.py

# Run proxy
docker run -d -p 11434:11434 distributed-ollama \
  python proxy/server.py --coordinator http://coordinator:8080
```

## 🤝 Contributing Resources

### As a Donor

Thank you for considering donating your compute! Here's what to expect:

- **Low impact**: Your machine handles requests only when idle
- **No privacy concerns**: Only model inference runs, no data is stored
- **Stop anytime**: Simply close the worker script with Ctrl+C
- **Community driven**: Help others run AI faster for free

### Optimizing Your Contribution

```bash
# Multiple GPUs? Run multiple workers
python worker/client.py --coordinator http://... --worker-id gpu-0
python worker/client.py --coordinator http://... --worker-id gpu-1 --ollama-port 11435

# More models = more requests
ollama pull llama2
ollama pull mistral  
ollama pull codellama
ollama pull phi
```

## 🛠️ Advanced Configuration

### Custom Coordinator Settings

```python
# coordinator/server.py
coordinator = CoordinatorServer(
    host="0.0.0.0",
    port=8080
)
coordinator.heartbeat_timeout = 30  # seconds before marking worker offline
```

### Worker with Custom Resources

```python
# worker/client.py
worker = OllamaWorker(
    coordinator_url="http://coordinator:8080",
    ollama_host="localhost",
    ollama_port=11434,
    worker_port=11435,
    worker_id="my-powerful-gpu"
)
```

### Load Balancing Strategy

The coordinator uses this priority system:

1. **Model availability**: Only workers with the requested model
2. **Worker status**: Idle workers first, then busy workers with <2 requests
3. **Available VRAM**: More free VRAM = higher priority
4. **Current load**: Fewer active requests = higher priority

## 📝 API Reference

### Coordinator API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workers/register` | POST | Register a new worker |
| `/api/workers/heartbeat` | POST | Worker heartbeat |
| `/api/generate` | POST | Generate text (Ollama compatible) |
| `/api/tags` | GET | List available models |
| `/api/status` | GET | Get coordinator status |

### Proxy API (Ollama Compatible)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/generate` | POST | Generate text |
| `/api/tags` | GET | List models |
| `/api/version` | GET | Get version |
| `/health` | GET | Health check |

## 🐛 Troubleshooting

### Worker Can't Connect to Ollama

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama if needed
ollama serve
```

### No Models Available

```bash
# Pull some models
ollama pull llama2
ollama pull mistral

# Verify
ollama list
```

### Worker Not Registering

```bash
# Check coordinator is running
curl http://coordinator:8080/api/status

# Check firewall isn't blocking
# On coordinator server, ensure port 8080 is open
```

### Requests Timing Out

- Check if any workers are active: `curl http://coordinator:8080/api/status`
- Verify the requested model is available on at least one worker
- Increase timeout in proxy settings

## 📊 Performance Tips

### For Best Performance

1. **Use workers with GPUs**: VRAM > 8GB recommended
2. **Download small models**: `phi` (2.7B) is fast, `llama2:7b` is good quality
3. **Run multiple workers**: More workers = more parallel capacity
4. **Locate workers near users**: Reduce network latency
5. **Keep workers updated**: Latest Ollama version = best performance

### Benchmarks (Example)

| Setup | Model | Generation Speed |
|-------|-------|------------------|
| Single RTX 4090 | llama2:7b | ~80 tokens/sec |
| 3x RTX 3080 | llama2:7b | ~240 tokens/sec (parallel) |
| 10x Mixed GPUs | llama2:7b | ~600+ tokens/sec (parallel) |

## 📜 License

MIT License - Feel free to use, modify, and distribute.

## 🙏 Acknowledgments

- Built for the [EditorAI](https://github.com/entity12208/EditorAI) project
- Powered by [Ollama](https://ollama.ai/)
- Thanks to all resource donors making this free!

## 📧 Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check the troubleshooting section above
- Review logs for error messages

---

**Made with ❤️ for the AI community**
