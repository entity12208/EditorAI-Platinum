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

## 👥 For Donors

Install Python from https://python.org, then `pip install -r requirements.txt`.
The worker can donate several kinds of backend — pick whichever you have:

**Local Ollama** (default)
```bash
ollama pull <model>          # download any model
python worker/client.py
```

**A llama.cpp server**
```bash
python worker/client.py --backend llamacpp --endpoint http://localhost:8080
```

**A hosted / custom OpenAI-compatible endpoint** (share an API key, a gateway,
or any custom endpoint). You choose exactly which model names to expose, and
the worker prompts for the key (hidden input) unless you pass `--api-key` /
set `EDITORAI_WORKER_API_KEY`:
```bash
python worker/client.py --backend openai \
    --endpoint https://api.example.com \
    --models glm-4.7-flash,glm-4.5-flash
```

> **Your privacy:** the worker never sends your IP address to the coordinator.
> The network is pull-based (your machine polls for work; the coordinator never
> connects back), so your address is never needed, transmitted, or stored.

---

## 📊 Monitoring

### Check Status

```bash
# See workers and stats
curl http://sn-1.vltgg.net:21800/api/status | python -m json.tool

# Check health
curl http://sn-1.vltgg.net:21800/health
```