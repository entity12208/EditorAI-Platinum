# Complete Setup Guide - TL;DR Version

This is the simplest possible guide to get everything running.

---

## For You (Server Owner) - 3 Methods

### Method 1: Automated Install (Easiest) ⭐

On your VPS:
```bash
# 1. Upload the install-server.sh script to your VPS
scp install-server.sh root@your-vps-ip:/root/

# 2. SSH into your VPS
ssh root@your-vps-ip

# 3. Run the installer
chmod +x install-server.sh
./install-server.sh
```

Done! The script will:
- Install all dependencies
- Set up the coordinator and proxy
- Configure firewall
- Start services automatically
- Give you your public URL

**Your URL will be:** `http://your-vps-ip:11434`

---

### Method 2: Docker (Also Easy)

On your VPS:
```bash
# 1. Install Docker and Docker Compose
curl -fsSL https://get.docker.com | sh
apt install docker-compose

# 2. Upload and extract the zip
cd /opt
unzip distributed-ollama.zip
cd distributed-ollama

# 3. Start everything
docker-compose up -d

# 4. Check status
docker-compose ps
docker-compose logs -f
```

**Your URL will be:** `http://your-vps-ip:11434`

---

### Method 3: Manual (Most Control)

On your VPS:
```bash
# 1. Install dependencies
apt update
apt install -y python3 python3-pip
pip3 install aiohttp psutil

# 2. Upload and extract the zip
cd /opt
unzip distributed-ollama.zip
cd distributed-ollama

# 3. Start coordinator
nohup python3 coordinator/server.py --host 0.0.0.0 --port 8080 > coordinator.log 2>&1 &

# 4. Start proxy
nohup python3 proxy/server.py --coordinator http://localhost:8080 --host 0.0.0.0 --port 11434 > proxy.log 2>&1 &

# 5. Open firewall ports
ufw allow 8080
ufw allow 11434
```

**Your URL will be:** `http://your-vps-ip:11434`

---

## For Donors - 2 Methods

### Method 1: Automated Setup (Easiest) ⭐

```bash
# 1. Download the setup-worker.sh script
# 2. Run it
chmod +x setup-worker.sh
./setup-worker.sh

# Follow the prompts - it will:
# - Install Ollama if needed
# - Download models
# - Set up the worker
# - Connect to your server
```

---

### Method 2: Manual Setup

**Windows:**
```cmd
1. Install Python from python.org (check "Add to PATH")
2. Install Ollama from ollama.ai
3. Open Command Prompt:
   ollama pull llama2
   ollama pull mistral
4. Download client.py and requirements.txt
5. pip install -r requirements.txt
6. python client.py --coordinator http://your-server-ip:8080
```

**Mac/Linux:**
```bash
# Install Ollama
curl https://ollama.ai/install.sh | sh

# Start Ollama
ollama serve &

# Download models
ollama pull llama2
ollama pull mistral

# Install dependencies
pip3 install aiohttp psutil

# Run worker
python3 client.py --coordinator http://your-server-ip:8080
```

---

## Verification

### Check Server is Running

```bash
curl http://your-vps-ip:11434/health
```

Should return:
```json
{
  "status": "healthy",
  "coordinator": "connected",
  "active_workers": 0
}
```

### Check Workers are Connected

```bash
curl http://your-vps-ip:8080/api/status
```

Should show your workers in the list.

### Test Generation

```bash
curl -X POST http://your-vps-ip:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"llama2","prompt":"Hello!","stream":false}'
```

---

## What to Share

### With EditorAI Users:
```
Change your Ollama URL in EditorAI settings to:
http://your-vps-ip:11434
```

### With Donors:
```
To donate your GPU:
1. Download setup-worker.sh
2. Run: ./setup-worker.sh
3. Enter coordinator URL: http://your-vps-ip:8080
4. Keep it running!

Or use the manual instructions in DONOR_GUIDE.md
```

---

## Monitoring

### View Status
```bash
# See active workers
curl http://localhost:8080/api/status | python3 -m json.tool

# Check logs (if using systemd)
journalctl -u ollama-coordinator -f
journalctl -u ollama-proxy -f

# Check logs (if using nohup)
tail -f coordinator.log
tail -f proxy.log

# Check logs (if using docker)
docker-compose logs -f
```

---

## Troubleshooting

### No workers showing up
1. Check donor ran the command correctly
2. Verify firewall allows port 8080
3. Check coordinator logs

### Requests failing
1. Verify at least one worker is connected
2. Check worker has the requested model installed
3. Look at logs for error messages

### Connection refused
1. Check services are running
2. Verify firewall is open
3. Test from server: `curl localhost:11434/health`

---

## Quick Reference

| Component | Port | URL |
|-----------|------|-----|
| Coordinator | 8080 | http://your-ip:8080 |
| Proxy (Public API) | 11434 | http://your-ip:11434 |
| Worker (internal) | 11434 | http://localhost:11434 |

**Commands:**
```bash
# Start services (systemd)
systemctl start ollama-coordinator
systemctl start ollama-proxy

# Stop services
systemctl stop ollama-coordinator
systemctl stop ollama-proxy

# View logs
journalctl -u ollama-coordinator -f

# Check status
systemctl status ollama-coordinator
curl http://localhost:8080/api/status
```

---

## Files Included

```
distributed-ollama/
├── install-server.sh           ← Run this on your VPS (automated)
├── setup-worker.sh             ← Donors run this (automated)
├── DONOR_GUIDE.md              ← Share this with donors
├── QUICKSTART.md               ← Quick start guide
├── README.md                   ← Full documentation
├── coordinator/server.py       ← Coordinator server
├── proxy/server.py             ← Public proxy
├── worker/client.py            ← Worker client
├── test.py                     ← Test suite
├── docker-compose.yml          ← Docker setup
└── docs/
    ├── SETUP_WALKTHROUGH.md    ← Detailed step-by-step
    ├── DEPLOYMENT.md           ← Production deployment
    ├── EDITORAI_INTEGRATION.md ← EditorAI integration
    └── ARCHITECTURE.md         ← System design
```

---

That's it! Choose your method and get started.

**Need help?** Check the detailed guides in the docs/ folder.
