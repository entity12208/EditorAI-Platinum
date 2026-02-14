# EditorAI Integration Guide

This guide explains how to integrate Distributed Ollama with EditorAI for faster AI-powered level generation.

## Overview

EditorAI is a Geometry Dash mod that uses AI to generate game levels. By default, it connects to a local Ollama instance at `http://localhost:11434`. With Distributed Ollama, you can connect to a network of donated GPUs instead, resulting in much faster generation times.

## Benefits

- **Faster Generation**: Multiple GPUs working in parallel
- **No Local GPU Required**: Use CPU-only machines
- **Free to Use**: No API costs
- **Better Quality**: Access to more powerful models
- **Always Available**: As long as donors are online

## Setup Steps

### 1. Find a Distributed Ollama Server

You need the URL of a running Distributed Ollama proxy server. This will look like:

```
http://ollama.example.com:11434
```

Or if running your own:

```
http://your-vps-ip:11434
```

### 2. Modify EditorAI Settings

EditorAI stores the Ollama URL in its mod settings. Here's how to change it:

#### Option A: Via EditorAI UI (Recommended)

1. Open Geometry Dash
2. Go to the level editor
3. Click the "AI" button in the editor
4. Click "Settings" or "Configure"
5. Find the "Ollama URL" field
6. Change from `http://localhost:11434` to your distributed server URL
7. Save settings

#### Option B: Direct Config File Edit

The exact location depends on your Geode installation, but typically:

**Windows**:
```
%LOCALAPPDATA%/GeometryDash/geode/config/entity12208.editorai.json
```

**macOS**:
```
~/Library/Application Support/GeometryDash/geode/config/entity12208.editorai.json
```

**Linux**:
```
~/.local/share/GeometryDash/geode/config/entity12208.editorai.json
```

Edit the JSON file:

```json
{
  "ollama-url": "http://your-distributed-ollama.com:11434",
  "model": "llama2",
  "temperature": 0.7
}
```

### 3. Test the Connection

1. Open EditorAI
2. Enter a prompt (e.g., "Create a simple platform level")
3. Click "Generate"
4. Watch for faster generation!

## Performance Comparison

| Setup | Model | Generation Time (avg) |
|-------|-------|----------------------|
| Local CPU | llama2:7b | ~3-5 minutes |
| Local GPU (GTX 1660) | llama2:7b | ~45 seconds |
| Distributed (3 GPUs) | llama2:7b | ~15-20 seconds |
| Distributed (10 GPUs) | llama2:7b | ~5-8 seconds |

*Times vary based on prompt complexity and network latency*

## Choosing Models

The distributed network may have multiple models available. Popular choices:

### For EditorAI:

1. **llama2:7b** (Recommended)
   - Good balance of quality and speed
   - Reliable for level generation
   - Moderate VRAM usage (~8GB)

2. **mistral:7b**
   - Faster than llama2
   - Good quality
   - Lower VRAM usage (~7GB)

3. **phi:2.7b**
   - Very fast
   - Lower quality but adequate
   - Minimal VRAM (~4GB)

4. **codellama:7b**
   - Optimized for structured output
   - May produce more consistent JSON
   - Similar to llama2 in speed

### Check Available Models

```bash
curl http://your-distributed-ollama.com:11434/api/tags
```

Or in EditorAI, the model dropdown should populate with available models.

## Troubleshooting

### Connection Failed

**Error**: "Failed to connect to Ollama"

**Solutions**:
1. Verify the URL is correct
2. Check if the server is online:
   ```bash
   curl http://your-server:11434/health
   ```
3. Ensure port 11434 is not blocked by firewall
4. Try using IP address instead of domain name

### No Models Available

**Error**: "Model not found"

**Solutions**:
1. Check available models:
   ```bash
   curl http://your-server:11434/api/tags
   ```
2. The model you selected might not be on any worker
3. Contact the server admin to add the model

### Slow Generation

**Possible Causes**:
1. No workers currently online
2. All workers are busy with other requests
3. Network latency is high
4. Model is too large for available VRAM

**Solutions**:
1. Check server status:
   ```bash
   curl http://your-server:11434/health
   ```
2. Try a smaller model (phi or mistral)
3. Wait for workers to become available
4. Use a server geographically closer to you

### Invalid Response

**Error**: "Failed to parse level data"

**Possible Causes**:
1. Model hallucinated invalid JSON
2. Response was cut off due to timeout
3. Model doesn't understand the prompt format

**Solutions**:
1. Try regenerating
2. Use a more reliable model (llama2)
3. Simplify your prompt
4. Check if the model supports JSON output

## Advanced Configuration

### Custom System Prompt

You can optimize EditorAI's prompts for distributed Ollama:

```json
{
  "system-prompt": "You are an expert Geometry Dash level designer. Generate levels in valid JSON format with 'objects' array. Keep responses under 1000 tokens.",
  "temperature": 0.7,
  "max-tokens": 2000
}
```

### Stream vs Non-Stream

EditorAI uses `stream: false` by default. This is correct for distributed setups as it:
- Reduces network overhead
- Ensures complete responses
- Works better with multiple workers

## Self-Hosting Tips

If you're running your own distributed network for EditorAI users:

### Recommended Setup

```
1 Coordinator + 1 Proxy on VPS (~$5-10/month)
↓
3-5 Workers with GPUs (community donated)
```

### Model Recommendations

Ask workers to install:
```bash
ollama pull llama2:7b
ollama pull mistral:7b  
ollama pull phi:2.7b
```

### Resource Requirements

For good performance with EditorAI:
- **Minimum**: 1 worker with 8GB VRAM
- **Recommended**: 3+ workers with 8GB+ VRAM each
- **Optimal**: 5+ workers with 12GB+ VRAM

### Monitoring

Set up monitoring to track:
- Active workers count
- Average response time
- Request success rate
- Model availability

Example monitoring script:

```bash
#!/bin/bash
while true; do
  curl -s http://localhost:8080/api/status | jq '.coordinator'
  sleep 60
done
```

## Community Contribution

### Running a Public Server

If you want to provide a distributed Ollama server for the EditorAI community:

1. **Deploy the infrastructure**:
   ```bash
   docker-compose up -d
   ```

2. **Announce the URL** in EditorAI community channels

3. **Monitor usage** and add workers as needed

4. **Set up TLS** for security:
   ```
   https://ollama.yourdomain.com
   ```

### Donating Workers

To contribute GPU resources:

1. **Install Ollama**:
   ```bash
   curl https://ollama.ai/install.sh | sh
   ```

2. **Pull recommended models**:
   ```bash
   ollama pull llama2:7b
   ollama pull mistral:7b
   ```

3. **Run worker**:
   ```bash
   python3 worker/client.py --coordinator http://public-server:8080
   ```

4. **Keep it running**! The more uptime, the more you help.

## API Usage Examples

### Direct API Call (for testing)

```bash
curl -X POST http://your-server:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "prompt": "Create a Geometry Dash level with the following theme: cyberpunk city. Include platforms, spikes, and orbs.",
    "stream": false,
    "temperature": 0.7
  }'
```

### Python Integration

```python
import requests

def generate_level(prompt, server_url="http://localhost:11434"):
    response = requests.post(
        f"{server_url}/api/generate",
        json={
            "model": "llama2",
            "prompt": f"Generate a Geometry Dash level: {prompt}",
            "stream": False,
            "temperature": 0.7
        }
    )
    return response.json()

level = generate_level("Create a hard level with many jumps")
print(level['response'])
```

## FAQ

### Q: Is this free to use?

**A:** Yes! The service is free as long as people donate their GPU resources.

### Q: Will my generations be faster?

**A:** Usually yes, especially if you don't have a powerful GPU locally. Speed depends on available workers.

### Q: Is my data private?

**A:** Your prompts are sent to the distributed network. Don't include sensitive information. Generated levels are not stored.

### Q: Can I still use local Ollama?

**A:** Yes! Just change the URL back to `http://localhost:11434` in settings.

### Q: What if the server is down?

**A:** You'll need to switch back to local Ollama or find another distributed server.

### Q: Can I run my own private network?

**A:** Absolutely! Follow the deployment guide and share the URL only with trusted users.

## Support

For EditorAI-specific issues:
- Check [EditorAI GitHub](https://github.com/entity12208/EditorAI)
- EditorAI Discord/Community

For Distributed Ollama issues:
- Check this project's README
- Open an issue on GitHub
- Test with curl to isolate problems

---

**Enjoy faster AI level generation! 🚀**
