# EditorAI Platinum — Distributed Inference Network

Free distributed computing system that lets users donate GPU/CPU resources —
or any AI provider endpoint they have access to — to run models for EditorAI
and other projects.

**Thank you [VLT.gg](https://vltgg.net) for the server making this possible!**

## 📋 For EditorAI Users

1. Change your Ollama URL in EditorAI settings to `http://sn-1.vltgg.net:21801`
   (deprecated — now, simply enable Platinum)
2. Set the Ollama model to any supported model (command listed below)

To list all models, run:

```bash
curl http://sn-1.vltgg.net:21801/api/tags
```

The API is Ollama-compatible and unchanged:

```bash
curl http://sn-1.vltgg.net:21801/api/generate \
  -d '{"model":"best","prompt":"hello","stream":true}'
```

`stream: true` streams tokens as NDJSON, one chunk per piece of text, ending
with `{"done": true}` — the same shape real Ollama uses, so any Ollama client
that accumulates chunks works. Omit `stream` (or send `false`) to get a single
buffered JSON object instead.

---

## 👥 For Donors

Install Python from https://python.org, then `pip install -r requirements.txt`.

A worker can host **as many providers as you like**. A provider is any URL that
speaks one of three API styles:

| style | request | typical providers |
|-----------|-----------------------------|-----------------------------------------------|
| `openai` | `POST /v1/chat/completions` | OpenAI, DeepSeek, llama.cpp, vLLM, LM Studio, OpenRouter, Groq, … |
| `ollama` | `POST /api/generate` | a local or remote Ollama server |
| `anthropic` | `POST /v1/messages` | Claude |

For each provider you either **map your own tags** onto specific upstream
models, or let the worker **autodetect** every model the endpoint reports. Tags
are what the network advertises, so anything you map shows up in `/api/tags`.

### Presets

```bash
python worker/client.py provider presets
```

Built-in presets (each still needs *your* API key when the upstream requires
one): `ollama`, `llamacpp`, `lmstudio`, `vllm`, `openai`, `anthropic`,
`deepseek`, `openrouter`, `groq`, `mistral`, `together`, `fireworks`,
`cerebras`, `xai`, `gemini`, `zhipu`, `perplexity`, plus `custom` for anything
else.

### Adding providers

The worker is a single self-contained file (`worker/client.py`). The fastest
way to add a bunch of endpoints at once is `add` — one URL per line, with an
optional key, models and headers; the API style and model list are detected
automatically:

```bash
# interactive — paste a list of endpoints, blank line when done
python worker/client.py add

# ...or from a file
python worker/client.py add --file endpoints.txt

# ...or straight on the command line (URL first, then optional key/models/headers)
python worker/client.py add \
    "https://api.deepseek.com sk-abc" \
    "https://api.openai.com sk-def models=fast=gpt-4o-mini,smart=o3" \
    "https://gw.example.com/v1 sk-xyz header='X-Org: acme' header='X-Env: prod'"
```

`add` is idempotent — re-pasting a URL updates it instead of duplicating it.
`models=` is only required for endpoints that can't be autodetected (the tool
tells you which ones those are). Fields: a bare token is the key, or use
`key=`, `key-env=`, `models=`, `header=`, `name=`, `style=`, `chat-path=`,
`models-path=`, `stream=false`, `retries=0` — all optional and in any order.

For one endpoint at a time, or full control:

```bash
# guided setup
python worker/client.py provider wizard

# a preset, autodetecting its whole catalogue (prompts for the key)
python worker/client.py provider add deepseek --preset deepseek --autodetect

# local Ollama — no key needed
python worker/client.py provider add local --preset ollama

# ANY url, with custom headers and hand-picked tags
python worker/client.py provider add mygw \
    --url https://gw.example.com/v1 \
    --header 'X-Org: acme' --header 'X-Trace: on' \
    --map fast=llama-3.1-8b --map smart=llama-3.1-70b

# keep the key out of the config file
python worker/client.py provider add openai --preset openai --key-env OPENAI_API_KEY

# a gateway with the key in a query param and no model-listing endpoint
python worker/client.py provider add odd \
    --url https://odd.example.com/api/v9 --chat-path /complete \
    --models-path - --auth query --auth-param access_token \
    --map odd-fast=their-model-name
```

Useful flags for `provider add` / `provider edit`:

| flag | meaning |
|-------------------------|--------------------------------------------------------|
| `--url` | provider base URL |
| `--style` | `openai` \| `ollama` \| `anthropic` |
| `--map TAG=MODEL` | advertise `TAG`, routed to `MODEL` (repeatable) |
| `--autodetect` | advertise every model the endpoint reports |
| `--include` / `--exclude` | glob filters over autodetected model ids |
| `--header 'Name: value'` | extra header, repeatable; `{api_key}` is substituted |
| `--key` / `--key-env` / `--key-stdin` | how to supply the API key |
| `--auth` | `auto` \| `bearer` \| `x-api-key` \| `query` \| `none` |
| `--chat-path` / `--models-path` | override endpoint paths (`-` = no listing) |
| `--extra-body JSON` | merged into every request body |
| `--no-qualify` | don't advertise `<provider>/<model>` aliases |
| `--timeout` | per-request timeout (default 300s) |
| `--stream` / `--no-stream` | stream from the endpoint (default on) vs wait for the whole reply |
| `--retries N` | extra attempts on transient upstream failures (5xx/524/timeouts; default 2) |

### Slow providers / gateway timeouts ("524 A timeout occurred")

Some upstreams — especially Cloudflare-fronted proxies like `justwoker.icu` —
kill long, idle connections after ~100s. The worker avoids this by
**streaming** from the endpoint by default (tokens keep flowing, so the
connection stays alive no matter how long generation takes), and it
automatically falls back to plain requests if an endpoint rejects
`stream=true`. Transient failures (`5xx`, `524`, connection resets, timeouts)
are retried a couple of times with a short backoff before being reported, so a
flaky gateway gets a second chance instead of failing the request outright.

Those tokens are also forwarded live: while generating, the worker reports
progress to the coordinator (`POST /api/progress/{id}`), which relays it to
whoever is waiting on `/api/generate` with `stream: true`. Workers and
coordinators that predate this still interoperate — an old worker simply
reports no progress, and the stream falls back to keepalives plus one final
line with the whole answer.

### Inspecting and running

```bash
python worker/client.py provider list          # what's configured
python worker/client.py provider models mygw   # ask the endpoint what it hosts
python worker/client.py provider test          # connectivity + auth for all
python worker/client.py provider test mygw --prompt 'hi'   # real generation
python worker/client.py tags                   # tag -> provider:model table

python worker/client.py run                    # donate, using every provider
python worker/client.py run --only deepseek,mygw
python worker/client.py run --concurrency 4
```

Providers live in one JSON file (`chmod 600`, it holds API keys):

```bash
python worker/client.py config-path
# override with PLATINUM_WORKER_CONFIG=/path/to/providers.json
```

**Hot reload:** edit providers while the worker runs. Adding, removing or
remapping tags is picked up within a few seconds and re-announced to the
coordinator — no restart, no dropped jobs. Disable with `--no-reload`.

### Tag precedence

1. explicit `--map` tags (your intent always wins)
2. autodetected model ids
3. `<provider>/<model>` aliases, always unambiguous

If two providers expose the same bare name, the earlier one wins it and the
other stays reachable through its qualified alias.

### Legacy usage (still supported)

```bash
python worker/client.py                                   # local Ollama
python worker/client.py --backend llamacpp --endpoint http://localhost:8080
python worker/client.py --backend openai \
    --endpoint https://api.example.com \
    --models glm-4.7-flash,glm-4.5-flash
```

These bypass the config file entirely and behave exactly as before, including
`--ollama-host` / `--ollama-port` / `--api-key` / `EDITORAI_WORKER_API_KEY`.

> **Your privacy:** the worker never sends your IP address to the coordinator.
> The network is pull-based (your machine polls for work; the coordinator never
> connects back), so your address is never needed, transmitted, or stored.
> API keys never leave your machine either — only the tag names do.

---

## 🛠 For Coordinator Operators

Fallback chains map a requested tag onto an ordered list of models to try.
The built-in table is unchanged; to define chains over your own tags, point
`PLATINUM_CHAINS` at a JSON file (re-read automatically when it changes):

```json
{
  "best":     [["mygw/llama-3.1-70b", 2], ["deepseek-chat", 1]],
  "cheapest": ["deepseek-chat", "fast"]
}
```

`[model, tries]` pairs, bare strings (1 try), or
`{"model": "x", "tries": 2}` objects all work. Tags without an entry get a
single attempt, so any tag a worker advertises is servable with no config.

---

## 📊 Monitoring

```bash
# See workers and stats (coordinator)
curl http://sn-1.vltgg.net:21800/api/status | python -m json.tool

# Check health (coordinator on :21800, public proxy on :21801)
curl http://sn-1.vltgg.net:21800/health
curl http://sn-1.vltgg.net:21801/health
```
