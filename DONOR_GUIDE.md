# 🎮 Donate Your GPU - Help Power EditorAI

Help the EditorAI community by sharing your unused GPU power. Make AI level generation faster for everyone!

---

## ⚡ Quick Setup (10 Minutes)

### Step 1: Install Ollama (3 minutes)

**Windows/Mac:** Download from https://ollama.ai/download and install  
**Linux:** `curl https://ollama.ai/install.sh | sh`

### Step 2: Install Python (2 minutes)

**Windows:** https://python.org/downloads ⚠️ **Check "Add Python to PATH"!**  
**Mac:** Already installed or `brew install python3`  
**Linux:** `sudo apt install python3 python3-pip`

### Step 3: Download Models (5+ minutes)

```bash
ollama pull llama2
ollama pull mistral
ollama pull phi
```

*Downloads are 2-4GB each. Takes 5-20 minutes depending on internet.*

### Step 4: Get Worker Files

Download these files from the project:
- `worker/client.py`
- `requirements.txt`

Save to a folder like `C:\ollama-worker\` or `~/ollama-worker/`

### Step 5: Install Dependencies

```bash
# Windows
cd C:\ollama-worker
pip install -r requirements.txt

# Mac/Linux
cd ~/ollama-worker
pip3 install -r requirements.txt
```

### Step 6: Start Donating! 🎉

```bash
# Windows
python client.py

# Mac/Linux
python3 client.py
```

**That's it!** Connects automatically to: `https://ollama-coordinator.onrender.com`

---

## ✅ What You'll See

```
====================================================================
Distributed Ollama Worker
====================================================================
Worker ID: abc-123-def-456
Coordinator: https://ollama-coordinator.onrender.com
====================================================================
✓ Ollama is running
Registering with coordinator...
Successfully registered with coordinator
Models available: llama2, mistral, phi
Resources:
  - CPU: 8 cores
  - RAM: 14.2/16.0 GB
  - VRAM: 22.5/24.0 GB (NVIDIA RTX 4090)
====================================================================
Worker is now active and accepting requests!
Press Ctrl+C to stop donating.
====================================================================
```

**Keep this window open while donating!**

---

## 🎯 What You're Donating

### ✅ Shared:
- GPU/VRAM (for AI inference when idle)
- CPU cores (for processing)
- RAM (for loading models)
- Internet bandwidth (minimal, just for requests)

### ❌ NOT Shared:
- Your personal files
- Your browsing data
- Your passwords
- Control of your computer

**You're only running AI inference - nothing else!**

---

## 💻 Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | GTX 1060 (6GB) | RTX 3060+ (12GB+) |
| CPU | 4 cores | 6+ cores |
| RAM | 8GB | 16GB+ |
| Storage | 20GB free | 50GB+ free |
| Internet | 10 Mbps | 50+ Mbps |

**No GPU?** You can still help with CPU-only! Install smaller models like `phi`.

---

## 📊 Model Recommendations

### For GPUs with 8GB+ VRAM:
```bash
ollama pull llama2      # Best quality
ollama pull mistral     # Fast & good
ollama pull codellama   # Code generation
```

### For GPUs with 4-6GB VRAM:
```bash
ollama pull phi         # Small but capable
ollama pull mistral     # Efficient
```

### For CPU-only (no GPU):
```bash
ollama pull phi         # Fast on CPU
ollama pull tinyllama   # Very small (1.1B)
```

Check what you have: `ollama list`

---

## ⏸️ Stop & Start

### Pause (Temporary)
Press **Ctrl+C** in the terminal

### Resume
Run the command again: `python client.py`

### Stop Permanently
1. Close the worker window
2. Uninstall Ollama (optional)
3. Delete the worker folder

---

## 🔧 Troubleshooting

### ❌ "Failed to connect to Ollama"

```bash
# Start Ollama
ollama serve

# Test it works
curl http://localhost:11434/api/tags
```

### ❌ "No models installed"

```bash
# Download models
ollama pull llama2
ollama pull mistral

# Check installed models
ollama list
```

### ❌ "Failed to register with coordinator"

**Causes:**
- Internet connection issue
- Coordinator is sleeping (Render free tier)

**Solutions:**
- Wait 30 seconds and try again
- Check: `curl https://ollama-coordinator.onrender.com/api/status`

### ❌ "Python not found"

**Windows:** Reinstall Python, check "Add Python to PATH"

### ❌ "pip not found"

```bash
# Windows
python -m pip install -r requirements.txt

# Mac/Linux
python3 -m pip install -r requirements.txt
```

---

## 💡 Advanced Options

### Run as Background Service

**Windows (NSSM):**
1. Download NSSM from https://nssm.cc
2. Run: `nssm install OllamaWorker`
3. Set path to Python and client.py
4. Start: `nssm start OllamaWorker`

**Linux/Mac (systemd):**
```bash
# Create service file
sudo nano /etc/systemd/system/ollama-worker.service
```

```ini
[Unit]
Description=Ollama Worker
After=network.target

[Service]
Type=simple
User=yourusername
WorkingDirectory=/path/to/ollama-worker
ExecStart=/usr/bin/python3 client.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable ollama-worker
sudo systemctl start ollama-worker
```

### Multiple GPUs

Run multiple workers:
```bash
# GPU 0
CUDA_VISIBLE_DEVICES=0 python client.py --worker-id gpu-0

# GPU 1
CUDA_VISIBLE_DEVICES=1 python client.py --worker-id gpu-1
```

### Custom Coordinator

Connect to different coordinator:
```bash
python client.py --coordinator http://custom-url.com:8080
```

---

## ❓ FAQ

**Q: Will this slow down my computer?**  
A: Only when processing requests. Stop it anytime with Ctrl+C.

**Q: How much electricity does this use?**  
A: Similar to gaming - 200-400W when processing. Mostly idle otherwise.

**Q: Can I game while running this?**  
A: Yes, but stop the worker for best gaming performance.

**Q: Is this safe?**  
A: Yes! Only runs AI models. Open source - verify the code yourself.

**Q: What if my computer restarts?**  
A: Just run the worker command again, or set up as a service.

**Q: How do I know it's working?**  
A: You'll see heartbeat messages every 10 seconds and activity when requests come in.

**Q: Can I donate only certain hours?**  
A: Yes! Run when you want, stop when you don't.

**Q: Does this work with AMD GPUs?**  
A: Ollama primarily supports NVIDIA. AMD is experimental. CPU-only works fine.

---

## 🏆 Thank You!

By donating your GPU, you're helping:
- **Students** without powerful hardware
- **Hobbyists** on creative projects
- **The EditorAI community** making game levels
- Making **AI accessible** to everyone

Every minute you donate makes a difference! 🙏

---

## 📞 Support

**Coordinator:** https://ollama-coordinator.onrender.com  
**Status Check:** https://ollama-coordinator.onrender.com/api/status

**Common Issues:**
1. Check Ollama is running: `ollama list`
2. Check Python is installed: `python --version`
3. Check internet connection: `ping google.com`
4. Wait 30s if coordinator is sleeping

---

## 🎯 Quick Commands Reference

```bash
# Start worker
python client.py

# Stop worker
Ctrl+C

# Check Ollama
ollama list

# Download model
ollama pull model-name

# Test Ollama
curl http://localhost:11434/api/tags

# Check coordinator
curl https://ollama-coordinator.onrender.com/api/status
```

---

## 🔗 Links

- **Ollama:** https://ollama.ai
- **Python:** https://python.org/downloads
- **EditorAI:** https://github.com/entity12208/EditorAI

---

**Ready to help? Follow the 6 steps above and start donating!** 🚀

Your GPU makes AI accessible to everyone. Thank you! 💚
