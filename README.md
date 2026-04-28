# Distributed Ollama Network

Free distributed computing system that lets users donate GPU/CPU resources to run Ollama models for EditorAI and other projects.

**Thank you [VLT.gg](https://vltgg.net) for the server making this possible!**

## 🚀 Quick Start

## 📋 For EditorAI Users

1. Change your Ollama URL in EditorAI settings to `http://sn-1.vltgg.net:21800` (depricated - now, simply enable Platinum)
2. Set the Ollama model to any supported model (command listed below)

To list all models, run:

```bash
curl http://sn-1.vltgg.net:21800/api/tags
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
curl http://sn-1.vltgg.net:21800/api/status | python -m json.tool

# Check health
curl http://sn-1.vltgg.net:21800/health
```