# Quick Start Guide

Get Distributed Ollama running in 5 minutes!

## Prerequisites

- Python 3.8 or higher
- For workers: Ollama installed

## Option 1: Quick Local Test

Test everything on one machine:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Terminal 1 - Start coordinator
python coordinator/server.py

# 3. Terminal 2 - Start proxy  
python proxy/server.py --coordinator http://localhost:8080

# 4. Terminal 3 - Start ollama
ollama serve

# 5. Terminal 4 - Start worker
python worker/client.py --coordinator http://localhost:8080

# 6. Terminal 5 - Test it!
python test.py
```

## Option 2: Docker (Easiest)

```bash
# Start coordinator and proxy
docker-compose up -d

# Run a worker (on any machine)
python worker/client.py --coordinator http://your-server-ip:8080
```

## Option 3: Production Deploy

### On a VPS (coordinator + proxy):

```bash
# Install
pip install -r requirements.txt

# Run coordinator
python coordinator/server.py --host 0.0.0.0 --port 8080 &

# Run proxy
python proxy/server.py --coordinator http://localhost:8080 --host 0.0.0.0 --port 11434 &
```

### On worker machines:

```bash
# Make sure Ollama is running
ollama serve &

# Pull some models
ollama pull llama2
ollama pull mistral

# Connect to coordinator
python worker/client.py --coordinator http://coordinator-ip:8080
```

## Verify It Works

```bash
# Check health
curl http://localhost:11434/health

# List models
curl http://localhost:11434/api/tags

# Generate text
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"llama2","prompt":"Hello!","stream":false}'
```

## Use with EditorAI

1. Change the Ollama URL in EditorAI settings to:
   ```
   http://your-server-ip:11434
   ```

2. Select a model from the dropdown

3. Start generating levels!

## Next Steps

- Read [README.md](README.md) for detailed documentation
- See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for production setup
- Check [EDITORAI_INTEGRATION.md](docs/EDITORAI_INTEGRATION.md) for EditorAI-specific tips

## Need Help?

Run the test suite:
```bash
python test.py --coordinator http://localhost:8080 --proxy http://localhost:11434
```

Check logs:
```bash
# Docker
docker-compose logs -f

# Manual
# Look at terminal output
```

## Common Issues

**"Connection refused"**
- Make sure the server is running
- Check firewall isn't blocking the port
- Try 127.0.0.1 instead of localhost

**"No models available"**
- At least one worker must be running
- Worker must have models installed: `ollama list`
- Pull models: `ollama pull llama2`

**"Request timeout"**
- All workers may be busy
- Try a smaller model
- Add more workers

---

That's it! You're ready to go. 🚀
