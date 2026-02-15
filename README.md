# Distributed Ollama Network

Free distributed computing system that lets users donate GPU/CPU resources to run Ollama models for EditorAI and other projects.

## 🚀 Quick Start

## 📋 For EditorAI Users

1. Change your Ollama URL in EditorAI settings to `https://ollama-proxy-sh88.onrender.com`
2. Set the Ollama model to any supported model (command listed below)

To list all models, run:

```bash
curl https://ollama-proxy-sh88.onrender.com/api/tags
```

---

## 👥 For GPU Donors

1. Install Ollama from https://ollama.ai
2. Install Python from https://python.org
3. Download any model of your choice with `ollama pull <model>`
4. Install and run worker:
```bash
pip install -r requirements.txt
python worker/client.py
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