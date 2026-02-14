# Complete Setup Guide: Server and Donors

This guide walks you through setting up the Distributed Ollama server and helping donors contribute their resources.

---

## Part 1: Setting Up the Server (For You)

You'll host the **Coordinator** and **Proxy** on a VPS or cloud server. This is what everyone connects to.

### Step 1: Get a VPS

**Recommended Providers:**
- DigitalOcean ($6/month)
- Linode ($5/month)
- Vultr ($6/month)
- Hetzner ($4/month)

**Minimum Requirements:**
- 1 vCPU
- 1GB RAM
- 25GB storage
- Ubuntu 20.04 or newer

### Step 2: Initial Server Setup

```bash
# SSH into your VPS
ssh root@your-vps-ip

# Update system
apt update && apt upgrade -y

# Install Python and dependencies
apt install -y python3 python3-pip git unzip

# Create a directory for the application
mkdir -p /opt/distributed-ollama
cd /opt/distributed-ollama
```

### Step 3: Upload Your Files

**Option A: Upload the zip file**
```bash
# On your local machine, upload the zip
scp distributed-ollama.zip root@your-vps-ip:/opt/distributed-ollama/

# On the VPS, extract it
cd /opt/distributed-ollama
unzip distributed-ollama.zip
cd distributed-ollama
```

**Option B: Use Git (if you put it on GitHub)**
```bash
cd /opt/distributed-ollama
git clone https://github.com/yourusername/distributed-ollama.git
cd distributed-ollama
```

### Step 4: Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

### Step 5: Start the Coordinator

```bash
# Start coordinator in the background
nohup python3 coordinator/server.py --host 0.0.0.0 --port 8080 > coordinator.log 2>&1 &
```

This will:
- Start the coordinator on port 8080
- Log output to `coordinator.log`
- Keep running even if you disconnect from SSH

### Step 6: Start the Proxy

```bash
# Start proxy in the background
nohup python3 proxy/server.py \
  --coordinator http://localhost:8080 \
  --host 0.0.0.0 \
  --port 11434 > proxy.log 2>&1 &
```

This will:
- Start the proxy on port 11434 (Ollama's default port)
- Connect to the coordinator
- Log output to `proxy.log`

### Step 7: Configure Firewall

```bash
# Allow necessary ports
ufw allow 22/tcp      # SSH (keep this!)
ufw allow 8080/tcp    # Coordinator
ufw allow 11434/tcp   # Proxy (public API)
ufw enable

# Check status
ufw status
```

### Step 8: Test the Server

```bash
# Check if coordinator is running
curl http://localhost:8080/api/status

# Check if proxy is running
curl http://localhost:11434/health

# From your local machine
curl http://your-vps-ip:11434/health
```

You should see something like:
```json
{
  "status": "healthy",
  "coordinator": "connected",
  "active_workers": 0,
  "requests_processed": 0
}
```

### Step 9: Make It Permanent (Optional but Recommended)

Instead of using `nohup`, set up systemd services so they auto-restart:

**Create coordinator service:**
```bash
nano /etc/systemd/system/ollama-coordinator.service
```

Paste this:
```ini
[Unit]
Description=Distributed Ollama Coordinator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/distributed-ollama/distributed-ollama
ExecStart=/usr/bin/python3 coordinator/server.py --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

**Create proxy service:**
```bash
nano /etc/systemd/system/ollama-proxy.service
```

Paste this:
```ini
[Unit]
Description=Distributed Ollama Proxy
After=network.target ollama-coordinator.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/distributed-ollama/distributed-ollama
ExecStart=/usr/bin/python3 proxy/server.py --coordinator http://localhost:8080 --host 0.0.0.0 --port 11434
Restart=always

[Install]
WantedBy=multi-user.target
```

**Enable and start services:**
```bash
systemctl daemon-reload
systemctl enable ollama-coordinator
systemctl enable ollama-proxy
systemctl start ollama-coordinator
systemctl start ollama-proxy

# Check status
systemctl status ollama-coordinator
systemctl status ollama-proxy
```

### Step 10: Check Logs

```bash
# View coordinator logs
journalctl -u ollama-coordinator -f

# View proxy logs
journalctl -u ollama-proxy -f

# Or if using nohup
tail -f /opt/distributed-ollama/distributed-ollama/coordinator.log
tail -f /opt/distributed-ollama/distributed-ollama/proxy.log
```

### Your Server URL

Your Ollama-compatible URL is now:
```
http://your-vps-ip:11434
```

Share this URL with:
- EditorAI users (they put this in their settings)
- Potential donors (they connect workers to your coordinator)

---

## Part 2: For Donors - How to Contribute Resources

Donors need to:
1. Install Ollama
2. Download some models
3. Run the worker script

### For Windows Users

#### Step 1: Install Python

1. Go to https://www.python.org/downloads/
2. Download Python 3.11 or newer
3. Run installer and **CHECK "Add Python to PATH"**
4. Click Install

#### Step 2: Install Ollama

1. Go to https://ollama.ai/download
2. Download Ollama for Windows
3. Install it
4. Ollama will start automatically in the background

#### Step 3: Download Models

Open Command Prompt and run:
```cmd
ollama pull llama2
ollama pull mistral
ollama pull phi
```

Wait for downloads to complete (this can take a while - models are several GB each).

#### Step 4: Download Worker Script

1. Download `worker/client.py` and `requirements.txt` from the distributed-ollama folder
2. Save them to a folder like `C:\ollama-worker\`

#### Step 5: Install Dependencies

Open Command Prompt in the worker folder:
```cmd
cd C:\ollama-worker
pip install -r requirements.txt
```

#### Step 6: Run the Worker

```cmd
python client.py --coordinator http://your-server-ip:8080
```

**You should see:**
```
====================================================================
Distributed Ollama Worker
====================================================================
Worker ID: abc-123-def-456
Coordinator: http://your-server-ip:8080
Local Ollama: http://localhost:11434
====================================================================
✓ Ollama is running
Registering with coordinator...
Successfully registered with coordinator
Worker ID: abc-123-def-456
Models available: llama2, mistral, phi
Resources:
  - CPU: 8 cores
  - RAM: 14.2/16.0 GB
  - VRAM: 22.5/24.0 GB (NVIDIA RTX 4090)
  - Disk: 456.3/1000.0 GB
====================================================================
Worker is now active and accepting requests!
Your resources are being shared with the network.
Press Ctrl+C to stop donating resources.
====================================================================
```

#### Step 7: Keep It Running

The worker needs to stay running to donate resources. You can:

**Option A: Keep the window open** (easiest)

**Option B: Run as a background service**
1. Download NSSM (https://nssm.cc/)
2. Run: `nssm install OllamaWorker python client.py --coordinator http://your-server-ip:8080`
3. Start service: `nssm start OllamaWorker`

---

### For Mac/Linux Users

#### Step 1: Install Ollama

```bash
curl https://ollama.ai/install.sh | sh
```

#### Step 2: Start Ollama

```bash
ollama serve &
```

#### Step 3: Download Models

```bash
ollama pull llama2
ollama pull mistral
ollama pull phi
```

#### Step 4: Download Worker Script

```bash
# Download the files
mkdir ~/ollama-worker
cd ~/ollama-worker
# Copy client.py and requirements.txt here
```

#### Step 5: Install Dependencies

```bash
pip3 install -r requirements.txt
```

#### Step 6: Run the Worker

```bash
python3 client.py --coordinator http://your-server-ip:8080
```

#### Step 7: Run as a Service (Optional)

Create a systemd service:
```bash
sudo nano /etc/systemd/system/ollama-worker.service
```

Paste:
```ini
[Unit]
Description=Ollama Worker
After=network.target

[Service]
Type=simple
User=yourusername
WorkingDirectory=/home/yourusername/ollama-worker
ExecStart=/usr/bin/python3 client.py --coordinator http://your-server-ip:8080
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable ollama-worker
sudo systemctl start ollama-worker
```

---

## Part 3: Verify Everything Works

### On the Server (Your End)

```bash
# Check coordinator status
curl http://localhost:8080/api/status
```

You should see at least one worker registered:
```json
{
  "coordinator": {
    "status": "running",
    "workers": 1,
    "active_workers": 1
  },
  "workers": [
    {
      "id": "abc-123",
      "address": "donor-ip:11435",
      "status": "idle",
      "vram": "22.5/24.0 GB",
      "gpu": "NVIDIA RTX 4090",
      "models": 3,
      "requests": "0 active / 0 total"
    }
  ]
}
```

### Test Generation

```bash
curl -X POST http://your-vps-ip:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "prompt": "Say hello!",
    "stream": false
  }'
```

You should get a response back with generated text!

---

## Part 4: For EditorAI Users

Once you have workers connected:

1. Open EditorAI
2. Go to AI settings
3. Change Ollama URL from `http://localhost:11434` to:
   ```
   http://your-vps-ip:11434
   ```
4. Save and restart if needed
5. Try generating a level!

---

## Troubleshooting

### "No workers available"

**Problem:** Coordinator has no workers registered

**Solution:**
1. Make sure at least one person is running the worker script
2. Check worker logs for connection errors
3. Verify coordinator is reachable: `curl http://your-server:8080/api/status`

### "Connection refused"

**Problem:** Can't connect to the server

**Solution:**
1. Check firewall allows port 11434: `ufw status`
2. Verify proxy is running: `systemctl status ollama-proxy`
3. Check logs: `journalctl -u ollama-proxy -f`

### "Model not found"

**Problem:** Worker doesn't have the requested model

**Solution:**
1. Tell donors to install the model: `ollama pull model-name`
2. Check available models: `curl http://your-server:11434/api/tags`

### Worker can't register

**Problem:** Worker script says "Failed to register"

**Solution:**
1. Check coordinator URL is correct
2. Verify port 8080 is open on your server
3. Make sure coordinator is running
4. Check coordinator logs for errors

---

## Quick Reference Card for Donors

Share this with people who want to donate:

```
=== How to Donate Your GPU to Distributed Ollama ===

1. Install Ollama: https://ollama.ai/download
2. Install Python: https://python.org/downloads
3. Download models:
   ollama pull llama2
   ollama pull mistral
4. Get worker script from: [your-github-or-download-link]
5. Install dependencies:
   pip install -r requirements.txt
6. Run worker:
   python client.py --coordinator http://your-server-ip:8080
7. Leave it running!

What you're donating:
✓ GPU/VRAM for AI inference
✓ CPU for processing
✓ A bit of internet bandwidth

What you're NOT donating:
✗ Personal data (never accessed)
✗ Storage (only for models you choose)
✗ Control of your computer

Stop anytime: Just close the worker window or press Ctrl+C
```

---

## Monitoring Your Network

### Dashboard Script

Save this as `monitor.sh`:
```bash
#!/bin/bash
while true; do
  clear
  echo "=== Distributed Ollama Status ==="
  curl -s http://localhost:8080/api/status | python3 -m json.tool
  echo ""
  echo "Press Ctrl+C to exit"
  sleep 5
done
```

Run: `bash monitor.sh`

---

That's it! Your distributed Ollama network is now running. As more donors join, your network gets faster and more capable!
