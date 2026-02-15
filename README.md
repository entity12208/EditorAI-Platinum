# Distributed Ollama Network

Free distributed computing system that lets users donate GPU/CPU resources to run Ollama models for EditorAI and other projects.

## 🚀 Quick Start

### Your Deployed URLs

**Coordinator:** `https://ollama-coordinator.onrender.com`  
**Public API:** `https://ollama-proxy-sh88.onrender.com`

### Deploy on Render.com (5 minutes)

1. Push this code to GitHub
2. Go to https://render.com (sign up free)
3. Click "New" → "Blueprint"
4. Connect your GitHub repo
5. Click "Apply"

Done! Render deploys both coordinator and proxy automatically.

### Test It Works

```bash
curl https://ollama-proxy-sh88.onrender.com/health
curl https://ollama-coordinator.onrender.com/api/status
```

---

## 📋 For EditorAI Users

Tell users to change their Ollama URL in EditorAI settings to:

```
https://ollama-proxy-sh88.onrender.com
```

That's it! They'll get faster AI generation powered by donated GPUs.

**Note:** First request may take 30 seconds (free tier wakes up), then it's fast.

---

## 👥 For GPU Donors

Share the **DONOR_GUIDE.md** file with people who want to donate their GPU.

**TL;DR for donors:**
```bash
# 1. Install Ollama from ollama.ai
# 2. Install Python from python.org
# 3. Download models
ollama pull llama2
ollama pull mistral

# 4. Install and run worker
pip install -r requirements.txt
python worker/client.py

# Connects automatically to your coordinator!
```

---

## 🏗️ Architecture

```
EditorAI Users
    ↓
https://ollama-proxy-sh88.onrender.com (Public API)
    ↓
https://ollama-coordinator.onrender.com (Routes requests)
    ↓
Worker 1 ← Worker 2 ← Worker 3 (Donated GPUs)
```

1. Workers register with coordinator (auto-detect GPU/VRAM)
2. EditorAI sends requests to proxy
3. Proxy forwards to coordinator
4. Coordinator picks best available worker
5. Worker generates response using local Ollama
6. Response flows back to EditorAI

---

## 📦 What's Included

```
distributed-ollama/
├── coordinator/server.py    # Manages workers, routes requests
├── proxy/server.py          # Public Ollama-compatible API
├── worker/client.py         # Worker client for donors
├── render.yaml              # Render.com deployment config
├── docker-compose.yml       # Docker deployment
├── requirements.txt         # Python dependencies
├── README.md               # This file
└── DONOR_GUIDE.md          # Share with GPU donors
```

---

## 🔧 Alternative Deployments

### Docker

```bash
docker-compose up -d
```

### Manual VPS Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Start coordinator
python coordinator/server.py --host 0.0.0.0 --port 8080 &

# Start proxy
python proxy/server.py --coordinator http://localhost:8080 --port 11434 &
```

### Fly.io (Always-on free option)

```bash
fly launch --name ollama-coordinator
fly launch --name ollama-proxy
```

---

## 📊 Monitoring

### Check Status

```bash
# See workers and stats
curl https://ollama-coordinator.onrender.com/api/status | python -m json.tool

# Check health
curl https://ollama-proxy-sh88.onrender.com/health
```

### View Logs (Render)

1. Go to Render dashboard
2. Click on service (coordinator or proxy)
3. Click "Logs" tab

### Response Format

```json
{
  "coordinator": {
    "status": "running",
    "workers": 3,
    "active_workers": 3
  },
  "workers": [
    {
      "id": "worker-abc-123",
      "status": "idle",
      "vram": "22.5/24.0 GB",
      "gpu": "NVIDIA RTX 4090",
      "models": 3,
      "requests": "0 active / 142 total"
    }
  ]
}
```

---

## 🧪 Testing

### Test Generation

```bash
curl -X POST https://ollama-proxy-sh88.onrender.com/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "prompt": "Create a level with platforms",
    "stream": false
  }'
```

### List Available Models

```bash
curl https://ollama-proxy-sh88.onrender.com/api/tags
```

---

## ⚙️ Configuration

### Environment Variables

**Coordinator:**
- `PORT` - Port to bind to (auto-set by Render)

**Proxy:**
- `PORT` - Port to bind to (auto-set by Render)

**Worker:**
- Coordinator URL embedded: `https://ollama-coordinator.onrender.com`
- Override with: `python worker/client.py --coordinator <url>`

### Models

Workers can install any Ollama models:
```bash
ollama pull llama2      # Best quality
ollama pull mistral     # Fast & good
ollama pull phi         # Smallest, fastest
ollama pull codellama   # For code
```

---

## 🐛 Troubleshooting

### "No workers available"

**Cause:** No donors connected yet.

**Solution:** 
- Share DONOR_GUIDE.md to get donors
- At least 1 person needs to run the worker

### "Service Unavailable" / "Connection refused"

**Cause:** Free tier servers sleep after 15 minutes.

**Solution:**
- Wait 30 seconds - server is waking up
- This is normal for free hosting
- First request wakes it up

**Optional fix:** Use UptimeRobot.com (free) to ping every 5 minutes

### "Request timeout"

**Cause:** All workers busy or complex prompt.

**Solutions:**
- Simplify prompt
- Add more workers
- Try different model (phi is fastest)

### Worker can't connect

**Donor should check:**
```bash
# Is Ollama running?
ollama list

# Is coordinator reachable?
curl https://ollama-coordinator.onrender.com/api/status

# Try running worker with verbose output
python worker/client.py
```

---

## 📈 Performance Tips

### For Best Performance

1. **Get more workers** - More GPUs = faster, more capacity
2. **Use powerful GPUs** - RTX 4090 > RTX 3080 > GTX 1660
3. **Multiple models** - llama2, mistral, phi covers most needs
4. **Keep services awake** - Use UptimeRobot to prevent cold starts

### Expected Generation Times

| Setup | Time |
|-------|------|
| Local CPU | 3-5 min |
| Single GPU donor | 30-45 sec |
| 3 GPU donors | 15-30 sec |
| 10+ GPU donors | 5-10 sec |

---

## 🔒 Security Notes

**Current version (v1.0) is for trusted networks.**

For production with untrusted users, add:
- API key authentication
- Rate limiting
- TLS/SSL encryption (use Cloudflare or nginx)
- Request validation
- Worker verification

---

## 💰 Cost

**Everything is FREE:**
- Render.com free tier (750 hrs/month)
- Workers donated by community
- No API costs

**Only cost: Your time**

**Optional upgrade:**
- Render paid tier: $7/month (no sleep mode)
- VPS: $5-10/month (Oracle Cloud is free forever)

---

## 🤝 Contributing

### As a Donor

Run the worker when you're not using your GPU:
```bash
python worker/client.py
```

### As a Developer

1. Fork the repository
2. Make improvements
3. Submit pull request

### Ideas for Improvement

- Add authentication
- Add streaming support
- Add model caching
- Add metrics dashboard
- Add request queuing
- Add multi-region support

---

## 📜 License

MIT License - Free to use, modify, and distribute.

---

## 🙏 Credits

- Built for [EditorAI](https://github.com/entity12208/EditorAI)
- Powered by [Ollama](https://ollama.ai)
- Thanks to all GPU donors!

---

## 📞 Support

**URLs:**
- Coordinator: https://ollama-coordinator.onrender.com
- Public API: https://ollama-proxy-sh88.onrender.com

**Check status:**
```bash
curl https://ollama-coordinator.onrender.com/api/status
```

**For issues:**
1. Check troubleshooting section above
2. Verify services are running on Render dashboard
3. Check logs for error messages
4. Test with curl commands

---

## 🎯 Quick Reference

| Task | Command |
|------|---------|
| Deploy | Push to GitHub → Render Blueprint |
| Check status | `curl .../api/status` |
| Test health | `curl .../health` |
| Test generation | `curl -X POST .../api/generate` |
| Share with EditorAI | URL: `https://ollama-proxy-sh88.onrender.com` |
| Share with donors | Give them `DONOR_GUIDE.md` |

---

**That's it! Deploy, share, and watch your distributed AI network grow.** 🚀
