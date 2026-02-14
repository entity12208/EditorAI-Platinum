# 🚀 Donate Your GPU - Simple Guide

Help make AI generation faster for everyone by donating your unused GPU power!

## What You're Donating

✅ **Your GPU/VRAM** - When you're not gaming or using it  
✅ **Some CPU & RAM** - Minimal impact  
✅ **A tiny bit of internet** - Only for AI requests  

❌ **NOT your personal data** - We never access it  
❌ **NOT your files** - Only AI models run  
❌ **NOT your control** - Stop anytime with Ctrl+C  

---

## Quick Setup (15 minutes)

### Step 1: Install Ollama (5 min)

**Windows/Mac:** Go to https://ollama.ai/download and install  
**Linux:** Run `curl https://ollama.ai/install.sh | sh`

### Step 2: Install Python (5 min)

**Download:** https://python.org/downloads  
⚠️ **Windows users:** Check "Add Python to PATH" during install!

### Step 3: Download Models (5+ min)

Open terminal/command prompt:

```bash
ollama pull llama2
ollama pull mistral
ollama pull phi
```

*This downloads ~15GB total. Takes 5-20 minutes depending on internet speed.*

### Step 4: Get the Worker Script

**Download these 2 files:**
1. `client.py` - [Download Link]
2. `requirements.txt` - [Download Link]

Save them to a folder like `C:\ollama-worker\` or `~/ollama-worker/`

### Step 5: Install Dependencies

In your terminal, go to the folder and run:

```bash
# Windows
cd C:\ollama-worker
pip install -r requirements.txt

# Mac/Linux
cd ~/ollama-worker
pip3 install -r requirements.txt
```

### Step 6: Start Donating!

```bash
# Windows
python client.py --coordinator http://YOUR-SERVER-URL:8080

# Mac/Linux
python3 client.py --coordinator http://YOUR-SERVER-URL:8080
```

Replace `YOUR-SERVER-URL` with: **[INSERT YOUR SERVER IP HERE]**

---

## What You'll See

```
====================================================================
Distributed Ollama Worker
====================================================================
Worker ID: abc-123-def-456
Coordinator: http://your-server:8080
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

**Leave this window open!** Your computer is now helping others generate AI content faster.

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | GTX 1060 (6GB) | RTX 3060+ (12GB+) |
| CPU | 4 cores | 6+ cores |
| RAM | 8GB | 16GB+ |
| Storage | 20GB free | 50GB+ free |
| Internet | 10 Mbps | 50+ Mbps |

**Don't have a GPU?** You can still help with CPU-only! Just install smaller models like `phi`.

---

## FAQ

**Q: Will this slow down my computer?**  
A: Only when processing requests. If you're gaming or doing heavy work, you can stop it anytime.

**Q: How much electricity does this use?**  
A: Similar to gaming - about 200-400W when actively processing.

**Q: Can I stop anytime?**  
A: Yes! Just press Ctrl+C in the terminal or close the window.

**Q: What if I restart my computer?**  
A: Just run the worker command again.

**Q: Is this safe?**  
A: Yes! The worker only runs AI inference - it never accesses your files or personal data.

**Q: How do I know it's working?**  
A: You'll see messages when requests come in, like:  
`2026-02-14 12:00:00 - INFO - Heartbeat sent`

**Q: Can I donate with multiple GPUs?**  
A: Yes! Just run multiple worker instances with different ports.

---

## Stopping Donation

**Temporary (pause):**
- Press `Ctrl+C` in the terminal

**Permanent (uninstall):**
1. Close the worker window
2. Uninstall Ollama if desired
3. Delete the worker folder

---

## Getting Help

**Connection Issues:**
```bash
# Test if Ollama is running
curl http://localhost:11434/api/tags
```

**Model Issues:**
```bash
# See what models you have
ollama list

# Pull a missing model
ollama pull model-name
```

**Worker Not Starting:**
- Make sure Ollama is running first
- Check Python is installed: `python --version`
- Verify dependencies: `pip install -r requirements.txt`

**Still stuck?**  
Contact: [Your Discord/Email/GitHub]

---

## Advanced: Run as Background Service

### Windows (NSSM)

1. Download NSSM: https://nssm.cc/
2. Open PowerShell as Admin:
```powershell
nssm install OllamaWorker
```
3. Set path to `python.exe` and arguments: `client.py --coordinator http://...`
4. Start service: `nssm start OllamaWorker`

### Linux/Mac (systemd/launchd)

See full guide at: [Link to SYSTEMD_SERVICES.md]

---

## Thank You! 🙏

By donating your GPU, you're helping:
- Students who can't afford powerful GPUs
- Hobbyists working on creative projects
- Open source developers building cool tools
- The EditorAI community making awesome game levels

Every bit helps make AI more accessible to everyone!

---

**Coordinator URL:** http://YOUR-SERVER-URL:8080  
**Support:** [Your contact info]  
**Project:** [GitHub link]
