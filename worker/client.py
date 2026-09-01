#!/usr/bin/env python3
"""
EditorAI Platinum — Worker client (single file: worker + provider layer + CLI).

Runs on contributor machines to donate compute to the EditorAI Platinum
network. A worker hosts as MANY PROVIDERS as you like — any URL that speaks
one of three API styles:

  openai     POST /v1/chat/completions   (OpenAI, DeepSeek, llama.cpp, vLLM,
                                          LM Studio, OpenRouter, Groq, ...)
  ollama     POST /api/generate          (a local or remote Ollama server)
  anthropic  POST /v1/messages           (Claude)

Presets exist for the common ones (you still supply an API key), and you can
add any number of your own endpoints with custom headers. For each provider
you either map your own tags onto specific upstream models, or let the worker
autodetect everything the endpoint reports.

Whatever the provider, the worker turns each job into an Ollama-style result,
so the coordinator, the proxy, and every existing client/worker keep seeing
exactly one protocol: `/api/tags` lists tags, `/api/generate` returns
`{"response": ..., "done": true}`.

Quick start (one file, no other modules needed):

  python client.py add                       # paste many URLs (URL + key + models)
  python client.py add --file endpoints.txt  # ...or read them from a file
  python client.py add "https://api.deepseek.com sk-abc" \
                       "https://gw.example.com/v1 sk-2 models=fast=llama-3.1-8b"
  python client.py provider presets
  python client.py provider add deepseek --preset deepseek --autodetect
  python client.py tags
  python client.py run

Legacy usage keeps working unchanged:

  python client.py                                   # local Ollama
  python client.py --backend llamacpp --endpoint http://localhost:8080
  python client.py --backend openai --endpoint https://api.example.com \
      --models glm-4.7-flash,glm-4.5-flash

PRIVACY: the worker NEVER sends your IP address to the coordinator. The
network is pull-based (workers poll the coordinator; it never dials back),
so your address is not needed for routing and is never transmitted or stored.
"""

import asyncio
import copy
import fnmatch
import getpass
import json
import logging
import os
import shlex
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import aiohttp
import psutil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CONFIG_VERSION = 1

# The public Platinum coordinator. Override per-run with --coordinator or
# the PLATINUM_COORDINATOR environment variable.
DEFAULT_COORDINATOR = 'http://sn-1.vltgg.net:21800'

# API styles the worker knows how to talk.
STYLE_OPENAI = 'openai'        # POST /v1/chat/completions
STYLE_OLLAMA = 'ollama'        # POST /api/generate
STYLE_ANTHROPIC = 'anthropic'  # POST /v1/messages
STYLES = (STYLE_OPENAI, STYLE_OLLAMA, STYLE_ANTHROPIC)

# Default request paths per style. A provider can override either one.
DEFAULT_CHAT_PATH = {
    STYLE_OPENAI: '/v1/chat/completions',
    STYLE_OLLAMA: '/api/generate',
    STYLE_ANTHROPIC: '/v1/messages',
}
DEFAULT_MODELS_PATH = {
    STYLE_OPENAI: '/v1/models',
    STYLE_OLLAMA: '/api/tags',
    STYLE_ANTHROPIC: '/v1/models',
}

# ── Presets ─────────────────────────────────────────────────────────────────
# A preset is just a starting point for `provider add --preset <name>`; every
# field can still be overridden, and the operator supplies the API key.
#   needs_key: informational — we prompt for a key when it is True.
#   autodetect: whether listing models from the endpoint usually works.
PRESETS: Dict[str, dict] = {
    'ollama': {
        'base_url': 'http://localhost:11434',
        'style': STYLE_OLLAMA, 'needs_key': False, 'autodetect': True,
        'desc': 'Local Ollama server',
    },
    'llamacpp': {
        'base_url': 'http://localhost:8080',
        'style': STYLE_OPENAI, 'needs_key': False, 'autodetect': True,
        'desc': 'llama.cpp server (OpenAI-compatible)',
    },
    'lmstudio': {
        'base_url': 'http://localhost:1234',
        'style': STYLE_OPENAI, 'needs_key': False, 'autodetect': True,
        'desc': 'LM Studio local server',
    },
    'vllm': {
        'base_url': 'http://localhost:8000',
        'style': STYLE_OPENAI, 'needs_key': False, 'autodetect': True,
        'desc': 'vLLM OpenAI-compatible server',
    },
    'openai': {
        'base_url': 'https://api.openai.com',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'OpenAI API',
    },
    'anthropic': {
        'base_url': 'https://api.anthropic.com',
        'style': STYLE_ANTHROPIC, 'needs_key': True, 'autodetect': True,
        'desc': 'Anthropic Claude API',
    },
    'deepseek': {
        'base_url': 'https://api.deepseek.com',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'DeepSeek API',
    },
    'openrouter': {
        'base_url': 'https://openrouter.ai/api',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'OpenRouter gateway (hundreds of models)',
    },
    'groq': {
        'base_url': 'https://api.groq.com/openai',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'Groq LPU cloud',
    },
    'mistral': {
        'base_url': 'https://api.mistral.ai',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'Mistral AI API',
    },
    'together': {
        'base_url': 'https://api.together.xyz',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'Together AI',
    },
    'fireworks': {
        'base_url': 'https://api.fireworks.ai/inference',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'Fireworks AI',
    },
    'cerebras': {
        'base_url': 'https://api.cerebras.ai',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'Cerebras inference cloud',
    },
    'xai': {
        'base_url': 'https://api.x.ai',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'xAI Grok API',
    },
    'gemini': {
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'chat_path': '/chat/completions', 'models_path': '/models',
        'desc': 'Google Gemini (OpenAI-compatible layer)',
    },
    'zhipu': {
        'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': False,
        'chat_path': '/chat/completions', 'models_path': '',
        'desc': 'Zhipu / GLM (BigModel) — list models manually',
    },
    'perplexity': {
        'base_url': 'https://api.perplexity.ai',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': False,
        'chat_path': '/chat/completions', 'models_path': '',
        'desc': 'Perplexity API (no model listing endpoint)',
    },
    'custom': {
        'base_url': '',
        'style': STYLE_OPENAI, 'needs_key': True, 'autodetect': True,
        'desc': 'Any other endpoint — you supply the URL',
    },
}


def preset_needs_key(preset: str) -> bool:
    return bool(PRESETS.get(preset, {}).get('needs_key', True))


def _host_of(url: str) -> str:
    rest = url.split('://', 1)[-1]
    return rest.split('/', 1)[0]


def detect_preset_for_url(url: str) -> str:
    """Guess which preset a pasted URL belongs to.

    Lets bulk import figure out the API style (and any odd paths) on its own,
    so someone pasting a list of endpoints doesn't have to say
    `--style anthropic` for the Claude line. Falls back to 'custom', i.e.
    plain OpenAI-compatible, which is what almost everything speaks."""
    host = _host_of(url).lower()
    if not host:
        return 'custom'
    best, best_len = 'custom', 0
    for name, spec in PRESETS.items():
        base = spec.get('base_url') or ''
        if not base:
            continue
        phost = _host_of(base).lower()
        if not phost:
            continue
        # Exact host, or the preset's host is a suffix of this one
        # (api.openai.com vs openai.com), scored by specificity.
        if host == phost or host.endswith('.' + phost) \
                or phost.endswith('.' + host):
            if len(phost) > best_len:
                best, best_len = name, len(phost)
    if best != 'custom':
        return best
    # Local Ollama's default port is a strong hint about the API style.
    if host.rsplit(':', 1)[-1] == '11434':
        return 'ollama'
    return 'custom'


def suggest_name(url: str, taken) -> str:
    """A short, stable, human-friendly provider name derived from a URL."""
    host = _host_of(url).lower()
    host, _, port = host.partition(':')
    host = host.strip()
    if not host:
        base = 'provider'
    elif host == 'localhost':
        base = f'localhost-{port}' if port else 'localhost'
    elif all(p.isdigit() for p in host.split('.')):
        # An IP address has no readable labels; use the port to tell apart
        # the many local servers people run this way.
        base = f'{host}-{port}' if port else host.replace('.', '-')
    else:
        parts = [p for p in host.split('.') if p]
        # Drop uninformative leading labels and the TLD.
        while len(parts) > 1 and parts[0] in ('api', 'www', 'open', 'openapi',
                                              'gateway', 'gw', 'inference'):
            parts.pop(0)
        if len(parts) > 1:
            parts = parts[:-1]
        base = '-'.join(parts) or 'provider'
    base = ''.join(c if (c.isalnum() or c in '-_') else '-' for c in base)
    base = base.strip('-') or 'provider'
    if base not in taken:
        return base
    i = 2
    while f'{base}-{i}' in taken:
        i += 1
    return f'{base}-{i}'


def _join(base: str, path: str) -> str:
    """Join a base URL and a path, tolerating a base that already carries the
    path's first segment (people habitually paste `.../v1`)."""
    base = (base or '').rstrip('/')
    if not path:
        return base
    if not path.startswith('/'):
        path = '/' + path
    first = path.split('/', 2)[1] if '/' in path[1:] + '/' else ''
    if first and base.endswith('/' + first):
        path = path[len(first) + 1:] or '/'
    return base + path


@dataclass
class ModelMap:
    """One advertised tag and the upstream model it runs on."""
    tag: str
    model: str

    def to_dict(self) -> dict:
        return {'tag': self.tag, 'model': self.model}


@dataclass
class Provider:
    """A single upstream endpoint the worker can serve models from."""
    name: str
    base_url: str = ''
    style: str = STYLE_OPENAI
    preset: str = 'custom'
    api_key: str = ''            # stored in the 0600 config file
    api_key_env: str = ''        # ...or read from this environment variable
    auth: str = 'auto'           # auto | bearer | x-api-key | query | none
    auth_param: str = 'key'      # query-string parameter when auth == 'query'
    headers: Dict[str, str] = field(default_factory=dict)
    chat_path: str = ''
    models_path: str = ''
    models: List[ModelMap] = field(default_factory=list)
    autodetect: bool = False
    include: List[str] = field(default_factory=list)   # fnmatch allow-list
    exclude: List[str] = field(default_factory=list)   # fnmatch deny-list
    qualify: bool = True         # also advertise "<name>/<model>" aliases
    enabled: bool = True
    timeout: int = 300
    extra_body: Dict[str, object] = field(default_factory=dict)

    # ── serialisation ───────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'base_url': self.base_url,
            'style': self.style,
            'preset': self.preset,
            'api_key': self.api_key,
            'api_key_env': self.api_key_env,
            'auth': self.auth,
            'auth_param': self.auth_param,
            'headers': dict(self.headers),
            'chat_path': self.chat_path,
            'models_path': self.models_path,
            'models': [m.to_dict() for m in self.models],
            'autodetect': self.autodetect,
            'include': list(self.include),
            'exclude': list(self.exclude),
            'qualify': self.qualify,
            'enabled': self.enabled,
            'timeout': self.timeout,
            'extra_body': dict(self.extra_body),
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Provider':
        style = d.get('style') or STYLE_OPENAI
        if style not in STYLES:
            logger.warning("provider %s: unknown style %r, assuming openai",
                           d.get('name'), style)
            style = STYLE_OPENAI
        models = []
        for m in d.get('models') or []:
            if isinstance(m, str):                 # ["gpt-4o", ...] shorthand
                models.append(ModelMap(m, m))
            elif isinstance(m, dict) and m.get('tag'):
                models.append(ModelMap(m['tag'], m.get('model') or m['tag']))
        return cls(
            name=d['name'],
            base_url=(d.get('base_url') or '').rstrip('/'),
            style=style,
            preset=d.get('preset') or 'custom',
            api_key=d.get('api_key') or '',
            api_key_env=d.get('api_key_env') or '',
            auth=d.get('auth') or 'auto',
            auth_param=d.get('auth_param') or 'key',
            headers=dict(d.get('headers') or {}),
            chat_path=d.get('chat_path') or '',
            models_path=d.get('models_path') if d.get('models_path') is not None else '',
            models=models,
            autodetect=bool(d.get('autodetect', False)),
            include=list(d.get('include') or []),
            exclude=list(d.get('exclude') or []),
            qualify=bool(d.get('qualify', True)),
            enabled=bool(d.get('enabled', True)),
            timeout=int(d.get('timeout') or 300),
            extra_body=dict(d.get('extra_body') or {}),
        )

    @classmethod
    def from_preset(cls, name: str, preset: str) -> 'Provider':
        spec = PRESETS.get(preset)
        if spec is None:
            raise ValueError(f"unknown preset: {preset} "
                             f"(known: {', '.join(sorted(PRESETS))})")
        return cls(
            name=name,
            base_url=spec.get('base_url', ''),
            style=spec.get('style', STYLE_OPENAI),
            preset=preset,
            chat_path=spec.get('chat_path', ''),
            models_path=spec.get('models_path', ''),
            autodetect=bool(spec.get('autodetect', False)),
        )

    # ── derived values ──────────────────────────────────────────────────
    def resolve_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env, '')
        return ''

    def chat_url(self) -> str:
        return _join(self.base_url,
                     self.chat_path or DEFAULT_CHAT_PATH[self.style])

    def models_url(self) -> Optional[str]:
        """None when model listing is not available for this provider."""
        if self.models_path == '-':      # explicit "no listing endpoint"
            return None
        path = self.models_path or DEFAULT_MODELS_PATH[self.style]
        if not path:
            return None
        return _join(self.base_url, path)

    def auth_mode(self) -> str:
        if self.auth != 'auto':
            return self.auth
        if not self.resolve_key():
            return 'none'
        return 'x-api-key' if self.style == STYLE_ANTHROPIC else 'bearer'

    def request_headers(self) -> Dict[str, str]:
        """Auth + custom headers. Custom headers win, so an operator can
        override anything (including Authorization) for odd gateways.
        `{api_key}` inside a header value is substituted."""
        key = self.resolve_key()
        headers: Dict[str, str] = {'Content-Type': 'application/json'}
        mode = self.auth_mode()
        if key and mode == 'bearer':
            headers['Authorization'] = f'Bearer {key}'
        elif key and mode == 'x-api-key':
            headers['x-api-key'] = key
        if self.style == STYLE_ANTHROPIC:
            headers.setdefault('anthropic-version', '2023-06-01')
        for k, v in self.headers.items():
            headers[k] = str(v).replace('{api_key}', key)
        return headers

    def query_params(self) -> Dict[str, str]:
        key = self.resolve_key()
        if key and self.auth_mode() == 'query':
            return {self.auth_param or 'key': key}
        return {}

    def tag_filter_ok(self, model_id: str) -> bool:
        if self.include and not any(fnmatch.fnmatch(model_id, p)
                                    for p in self.include):
            return False
        if any(fnmatch.fnmatch(model_id, p) for p in self.exclude):
            return False
        return True

    def redacted(self) -> dict:
        d = self.to_dict()
        if d['api_key']:
            tail = d['api_key'][-4:] if len(d['api_key']) > 8 else ''
            d['api_key'] = f'***{tail}' if tail else '***'
        d['headers'] = {k: ('***' if 'key' in k.lower() or 'auth' in k.lower()
                            or 'token' in k.lower() else v)
                        for k, v in d['headers'].items()}
        return d


class ProviderStore:
    """The provider list on disk (JSON, chmod 600)."""

    def __init__(self, path: Optional[str] = None):
        self.path = os.path.abspath(os.path.expanduser(path or default_config_path()))
        self.providers: List[Provider] = []
        self.settings: Dict[str, object] = {}
        self.load()

    # ── io ──────────────────────────────────────────────────────────────
    def load(self) -> None:
        try:
            with open(self.path) as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            raise RuntimeError(f"could not read {self.path}: {e}") from e
        self.settings = dict(data.get('settings') or {})
        self.providers = []
        for d in data.get('providers') or []:
            try:
                self.providers.append(Provider.from_dict(d))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("skipping bad provider entry in %s: %s",
                               self.path, e)

    def save(self) -> None:
        payload = {
            'version': CONFIG_VERSION,
            'settings': self.settings,
            'providers': [p.to_dict() for p in self.providers],
        }
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(payload, f, indent=2)
            f.write('\n')
        try:                                  # API keys live in here
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(tmp, self.path)

    # ── crud ────────────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[Provider]:
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def add(self, provider: Provider, overwrite: bool = False) -> None:
        existing = self.get(provider.name)
        if existing is not None:
            if not overwrite:
                raise ValueError(f"provider '{provider.name}' already exists "
                                 f"(use `provider edit` or --force)")
            self.providers[self.providers.index(existing)] = provider
        else:
            self.providers.append(provider)

    def remove(self, name: str) -> bool:
        p = self.get(name)
        if p is None:
            return False
        self.providers.remove(p)
        return True

    def enabled_providers(self) -> List[Provider]:
        return [p for p in self.providers if p.enabled]


def default_config_path() -> str:
    """PLATINUM_WORKER_CONFIG > XDG config dir > ~/.editorai-platinum."""
    env = os.environ.get('PLATINUM_WORKER_CONFIG')
    if env:
        return env
    xdg = os.environ.get('XDG_CONFIG_HOME')
    base = xdg if xdg else os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'editorai-platinum', 'providers.json')


class ProviderClient:
    """HTTP adapter: one instance per provider, speaks that provider's style."""

    def __init__(self, provider: Provider):
        self.p = provider

    # ── model discovery ─────────────────────────────────────────────────
    async def list_models(self, session: aiohttp.ClientSession) -> List[str]:
        """Ask the endpoint what models it has. Empty list on any failure —
        callers fall back to the operator's explicit tag mappings."""
        url = self.p.models_url()
        if not url:
            return []
        try:
            async with session.get(
                    url, headers=self.p.request_headers(),
                    params=self.p.query_params() or None,
                    timeout=aiohttp.ClientTimeout(total=20)) as r:
                body = await r.text()
                if r.status != 200:
                    logger.warning("[%s] model listing HTTP %s: %s",
                                   self.p.name, r.status, body[:200])
                    return []
                data = json.loads(body)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            logger.warning("[%s] model listing failed: %s", self.p.name, e)
            return []
        return _extract_model_ids(data)

    # ── generation ──────────────────────────────────────────────────────
    async def generate(self, session: aiohttp.ClientSession, model: str,
                       prompt: str, options: dict) -> dict:
        """Run one prompt. Always returns an Ollama-shaped result dict, i.e.
        {'model': ..., 'response': text, 'done': True} (plus whatever extra
        fields a real Ollama backend returned), so the coordinator, the proxy
        and every existing client see the exact same protocol as before."""
        if self.p.style == STYLE_OLLAMA:
            return await self._generate_ollama(session, model, prompt, options)
        if self.p.style == STYLE_ANTHROPIC:
            return await self._generate_anthropic(session, model, prompt, options)
        return await self._generate_openai(session, model, prompt, options)

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=max(5, int(self.p.timeout or 300)))

    async def _post(self, session: aiohttp.ClientSession, body: dict) -> dict:
        url = self.p.chat_url()
        async with session.post(url, json=body,
                                headers=self.p.request_headers(),
                                params=self.p.query_params() or None,
                                timeout=self._timeout()) as r:
            text = await r.text()
            if r.status != 200:
                raise RuntimeError(f"{self.p.name} HTTP {r.status}: {text[:500]}")
            try:
                return json.loads(text)
            except ValueError as e:
                raise RuntimeError(f"{self.p.name}: non-JSON reply: "
                                   f"{text[:200]}") from e

    async def _generate_ollama(self, session, model, prompt, options) -> dict:
        body = {'model': model, 'prompt': prompt, 'stream': False,
                'options': options or {}}
        body.update(copy.deepcopy(self.p.extra_body))
        data = await self._post(session, body)
        # Already Ollama-shaped; pass through untouched (compat with the
        # original single-backend worker, which forwarded the raw JSON).
        return data

    async def _generate_openai(self, session, model, prompt, options) -> dict:
        body = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'stream': False,
        }
        _apply_sampling(body, options, max_key='max_tokens')
        body.update(copy.deepcopy(self.p.extra_body))
        data = await self._post(session, body)
        text = _extract_openai_text(data)
        out = {'model': model, 'response': text, 'done': True}
        usage = data.get('usage') if isinstance(data, dict) else None
        if isinstance(usage, dict):
            out['prompt_eval_count'] = usage.get('prompt_tokens')
            out['eval_count'] = usage.get('completion_tokens')
        return out

    async def _generate_anthropic(self, session, model, prompt, options) -> dict:
        body = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 4096,
            'stream': False,
        }
        _apply_sampling(body, options, max_key='max_tokens')
        body.update(copy.deepcopy(self.p.extra_body))
        data = await self._post(session, body)
        text = _extract_anthropic_text(data)
        out = {'model': model, 'response': text, 'done': True}
        usage = data.get('usage') if isinstance(data, dict) else None
        if isinstance(usage, dict):
            out['prompt_eval_count'] = usage.get('input_tokens')
            out['eval_count'] = usage.get('output_tokens')
        return out

    async def probe(self, session: aiohttp.ClientSession) -> Tuple[bool, str]:
        """Connectivity check used by `provider test` and worker startup."""
        url = self.p.models_url()
        if not url:
            return True, 'no model-listing endpoint (nothing to probe)'
        try:
            async with session.get(
                    url, headers=self.p.request_headers(),
                    params=self.p.query_params() or None,
                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    ids = _extract_model_ids(json.loads(await r.text()))
                    return True, f'{len(ids)} model(s) visible'
                if r.status in (401, 403):
                    return False, f'HTTP {r.status} — check the API key'
                return False, f'HTTP {r.status}: {(await r.text())[:200]}'
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            return False, f'{type(e).__name__}: {e}' if str(e) else type(e).__name__


def _apply_sampling(body: dict, options: Optional[dict], max_key: str) -> None:
    """Translate the Ollama sampling knobs the coordinator forwards."""
    if not isinstance(options, dict):
        return
    if 'temperature' in options:
        body['temperature'] = options['temperature']
    if 'top_p' in options:
        body['top_p'] = options['top_p']
    num_predict = options.get('num_predict')
    if isinstance(num_predict, int) and num_predict > 0:
        body[max_key] = num_predict
    stop = options.get('stop')
    if stop:
        body['stop'] = stop


def _extract_model_ids(data) -> List[str]:
    """Pull model names out of whatever listing shape came back.

    Handles OpenAI (`{"data":[{"id":...}]}`), Ollama
    (`{"models":[{"name":...}]}`), Anthropic (`{"data":[{"id":...}]}`) and a
    couple of bare-list variants seen on custom gateways."""
    out: List[str] = []
    if isinstance(data, dict):
        for key in ('data', 'models', 'result', 'items'):
            items = data.get(key)
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, str):
                        out.append(it)
                    elif isinstance(it, dict):
                        for k in ('id', 'name', 'model', 'model_name'):
                            if isinstance(it.get(k), str):
                                out.append(it[k])
                                break
                if out:
                    break
    elif isinstance(data, list):
        for it in data:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                for k in ('id', 'name', 'model'):
                    if isinstance(it.get(k), str):
                        out.append(it[k])
                        break
    # De-dupe, keep order.
    seen, uniq = set(), []
    for m in out:
        if m and m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def _extract_openai_text(data) -> str:
    try:
        choice = data['choices'][0]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError('no choices in chat-completions reply') from e
    msg = choice.get('message') or {}
    content = msg.get('content')
    if isinstance(content, list):        # some gateways return content parts
        content = ''.join(part.get('text', '') for part in content
                          if isinstance(part, dict))
    if not content:
        content = choice.get('text') or ''
    if not isinstance(content, str) or not content:
        # Reasoning-only replies happen; surface them rather than an empty
        # response so the coordinator's fallback chain can react.
        reasoning = msg.get('reasoning_content') or msg.get('reasoning')
        if isinstance(reasoning, str) and reasoning:
            return reasoning
        raise RuntimeError('no content in chat-completions reply')
    return content


def _extract_anthropic_text(data) -> str:
    blocks = data.get('content') if isinstance(data, dict) else None
    if isinstance(blocks, list):
        text = ''.join(b.get('text', '') for b in blocks
                       if isinstance(b, dict) and b.get('type', 'text') == 'text')
        if text:
            return text
    raise RuntimeError('no content in messages reply')


@dataclass
class Route:
    """Where an advertised tag actually goes."""
    tag: str
    provider: Provider
    model: str

    @property
    def client(self) -> ProviderClient:
        return ProviderClient(self.provider)


class ModelRegistry:
    """tag -> Route, built from explicit mappings plus optional autodetection.

    Precedence, highest first:
      1. explicit `models` mappings on a provider (operator intent)
      2. autodetected upstream model ids
      3. qualified `"<provider>/<model>"` aliases (always unambiguous)
    Earlier providers in the config win a contested bare tag; the qualified
    alias always remains available for the loser.
    """

    def __init__(self):
        self.routes: Dict[str, Route] = {}

    def tags(self) -> List[str]:
        return sorted(self.routes)

    def resolve(self, tag: str) -> Optional[Route]:
        route = self.routes.get(tag)
        if route is not None:
            return route
        # Be forgiving about case and the ":latest" suffix Ollama clients add.
        lowered = tag.lower()
        for t, r in self.routes.items():
            if t.lower() == lowered:
                return r
        if lowered.endswith(':latest'):
            return self.resolve(tag[: -len(':latest')])
        return None

    def _claim(self, tag: str, provider: Provider, model: str,
               force: bool = False) -> None:
        if not tag:
            return
        if tag in self.routes and not force:
            other = self.routes[tag]
            if other.provider.name != provider.name or other.model != model:
                logger.info("tag %r already served by %s/%s — %s/%s is "
                            "reachable as %s/%s", tag, other.provider.name,
                            other.model, provider.name, model, provider.name,
                            model)
            return
        self.routes[tag] = Route(tag, provider, model)

    async def build(self, providers: List[Provider],
                    session: aiohttp.ClientSession) -> 'ModelRegistry':
        detected: Dict[str, List[str]] = {}
        detect_targets = [p for p in providers if p.autodetect]
        if detect_targets:
            results = await asyncio.gather(*[
                ProviderClient(p).list_models(session) for p in detect_targets
            ], return_exceptions=True)
            for p, res in zip(detect_targets, results):
                if isinstance(res, Exception):
                    logger.warning("[%s] autodetect failed: %s", p.name, res)
                    detected[p.name] = []
                else:
                    kept = [m for m in res if p.tag_filter_ok(m)]
                    detected[p.name] = kept
                    logger.info("[%s] autodetected %d model(s)%s",
                                p.name, len(kept),
                                '' if len(kept) == len(res)
                                else f' ({len(res) - len(kept)} filtered out)')

        # 1. explicit mappings
        for p in providers:
            for m in p.models:
                self._claim(m.tag, p, m.model, force=True)
        # 2. autodetected ids
        for p in providers:
            for model_id in detected.get(p.name, []):
                self._claim(model_id, p, model_id)
        # 3. qualified aliases
        for p in providers:
            if not p.qualify:
                continue
            models = {m.model for m in p.models} | set(detected.get(p.name, []))
            for model_id in sorted(models):
                self._claim(f'{p.name}/{model_id}', p, model_id)
        return self

    def describe(self) -> List[Tuple[str, str, str]]:
        return [(t, r.provider.name, r.model)
                for t, r in sorted(self.routes.items())]


# ════════════════════════════════════════════════════════════════════════════
# CLI (provider management + bulk add)
# ════════════════════════════════════════════════════════════════════════════

def _parse_headers(values: Optional[List[str]]) -> Dict[str, str]:
    """--header 'X-Foo: bar' (also accepts 'X-Foo=bar')."""
    out: Dict[str, str] = {}
    for raw in values or []:
        if ':' in raw:
            k, v = raw.split(':', 1)
        elif '=' in raw:
            k, v = raw.split('=', 1)
        else:
            raise SystemExit(f"bad --header {raw!r}: use 'Name: value'")
        k = k.strip()
        if not k:
            raise SystemExit(f"bad --header {raw!r}: empty name")
        out[k] = v.strip()
    return out


def _parse_maps(values: Optional[List[str]]) -> List[ModelMap]:
    """--map tag=upstream-model (repeatable, comma-separated also allowed).

    A bare `--map gpt-4o` maps the tag to the identically named model."""
    out: List[ModelMap] = []
    for raw in values or []:
        for piece in raw.split(','):
            piece = piece.strip()
            if not piece:
                continue
            if '=' in piece:
                tag, model = piece.split('=', 1)
            else:
                tag = model = piece
            tag, model = tag.strip(), model.strip()
            if not tag or not model:
                raise SystemExit(f"bad --map {piece!r}: use tag=model")
            out.append(ModelMap(tag, model))
    return out


def _parse_json_obj(raw: Optional[str], what: str) -> Dict[str, object]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise SystemExit(f"bad {what}: {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"bad {what}: expected a JSON object")
    return data


def _csv(raw: Optional[str]) -> List[str]:
    return [x.strip() for x in (raw or '').split(',') if x.strip()]


def _prompt_key(name: str, preset: str) -> str:
    if not sys.stdin.isatty():
        # Non-interactive (scripts, CI, `| tee`): never block, and don't let
        # getpass echo the key into a log.
        return ''
    try:
        return getpass.getpass(
            f"API key for '{name}' (hidden, blank = none): ").strip()
    except (EOFError, KeyboardInterrupt):
        return ''


def _print_table(rows: List[List[str]], headers: List[str]) -> None:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    line = '  '.join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print('  '.join('-' * widths[i] for i in range(len(headers))))
    for r in rows:
        print('  '.join(r[i].ljust(widths[i]) for i in range(len(headers))))


# ── bulk add ────────────────────────────────────────────────────────────────
BULK_HELP = """\
One endpoint per line. The URL comes first; everything after it is optional:

  https://api.deepseek.com
  https://api.deepseek.com  sk-abc123
  https://api.openai.com    sk-abc  models=fast=gpt-4o-mini,smart=o3
  https://gw.example.com/v1 sk-xyz  header='X-Org: acme'  header='X-Env: prod'
  https://odd.example.com   sk-1    name=odd  style=anthropic
  http://localhost:11434

Fields (all optional, any order, `|` also works as a separator):
  <bare token>        the API key (same as key=...)
  key=KEY             API key
  key-env=VAR         read the key from this environment variable instead
  models=A,B          models to advertise; `tag=model` renames them
  header='N: V'       extra header (repeatable)
  name=NAME           provider name (default: derived from the URL)
  style=STYLE         openai | ollama | anthropic (default: guessed)
  chat-path=/p        override the generation path
  models-path=/p      override the model-listing path ('-' = none)
Anything you leave out is worked out automatically: the API style is guessed
from the URL, and the model list is autodetected from the endpoint. Only
endpoints that can't be autodetected need models=.
"""


def _split_fields(line: str) -> List[str]:
    """Tokenise one bulk line. Supports `|` separators and shell-style quotes
    so `header='X-Org: acme'` survives intact."""
    if '|' in line:
        return [t.strip() for t in line.split('|') if t.strip()]
    try:
        return shlex.split(line)
    except ValueError:
        # Unbalanced quote — fall back to plain whitespace splitting rather
        # than throwing away the operator's line.
        return line.split()


def parse_bulk_line(line: str, taken) -> Tuple[Optional[Provider], str, set]:
    """Turn one line into a Provider.

    Returns (provider, error_message, provided_fields). `provided_fields` is
    the set of field kinds the operator actually wrote on the line
    (name/key/key-env/models/headers/style/chat-path/models-path), so the
    bulk command can merge re-adds of the same URL instead of overwriting
    fields they didn't mention."""
    line = line.strip()
    if not line or line.startswith('#'):
        return None, '', set()
    fields = _split_fields(line)
    if not fields:
        return None, '', set()
    url = fields[0].rstrip(',')
    if url.lower().startswith('url='):
        url = url[4:]
    if '://' not in url:
        # Be forgiving: a bare host is almost certainly meant to be http(s).
        if url.startswith('localhost') or url.startswith('127.0.0.1'):
            url = 'http://' + url
        elif '.' in url or ':' in url:
            url = 'https://' + url
        else:
            return None, f"{fields[0]!r} does not look like a URL", set()

    name = key = key_env = style = chat_path = models_path = ''
    models_spec = ''
    headers: List[str] = []
    provided: set = set()
    for raw in fields[1:]:
        tok = raw.strip().rstrip(',')
        if not tok:
            continue
        low = tok.lower()
        if '=' not in tok:
            if key:
                return None, f"unexpected extra value {tok!r}", provided
            key = tok
            provided.add('key')
            continue
        field, _, value = tok.partition('=')
        f = field.strip().lower().replace('_', '-')
        value = value.strip()
        if f in ('key', 'apikey', 'api-key', 'token'):
            key = value
            provided.add('key')
        elif f in ('key-env', 'keyenv', 'env'):
            key_env = value
            provided.add('key-env')
        elif f in ('models', 'model', 'map', 'tags'):
            models_spec = f'{models_spec},{value}' if models_spec else value
            provided.add('models')
        elif f in ('header', 'headers'):
            headers.append(value)
            provided.add('headers')
        elif f == 'name':
            name = value
            provided.add('name')
        elif f == 'style':
            style = value
            provided.add('style')
        elif f in ('chat-path', 'chatpath'):
            chat_path = value
            provided.add('chat-path')
        elif f in ('models-path', 'modelspath'):
            models_path = value
            provided.add('models-path')
        elif not key and low.count('=') == 0:
            key = tok
            provided.add('key')
        else:
            # An unrecognised `a=b` is most likely a tag mapping the operator
            # forgot to prefix with models=.
            models_spec = f'{models_spec},{tok}' if models_spec else tok
            provided.add('models')

    preset = detect_preset_for_url(url)
    p = Provider.from_preset(name or suggest_name(url, taken), preset)
    p.base_url = url.rstrip('/')
    if style:
        if style not in STYLES:
            return None, f"unknown style {style!r} (use {'/'.join(STYLES)})", provided
        p.style = style
    if chat_path:
        p.chat_path = chat_path
    if models_path:
        p.models_path = models_path
    if key_env:
        p.api_key_env = key_env
    elif key:
        p.api_key = key
    if headers:
        try:
            p.headers.update(_parse_headers(headers))
        except SystemExit as e:
            return None, str(e), provided
    if models_spec:
        try:
            p.models = _parse_maps([models_spec])
        except SystemExit as e:
            return None, str(e), provided
    # Autodetect whenever the operator didn't pin models and the endpoint has
    # somewhere to ask. models= is therefore only needed when detection fails.
    p.autodetect = not p.models and p.models_url() is not None
    return p, '', provided


def _read_bulk_lines(args) -> List[str]:
    """Gather bulk lines from --file, positional args, stdin, or a prompt."""
    lines: List[str] = []
    if args.file:
        for path in args.file:
            if path == '-':
                lines.extend(sys.stdin.read().splitlines())
                continue
            try:
                with open(os.path.expanduser(path)) as f:
                    lines.extend(f.read().splitlines())
            except OSError as e:
                raise SystemExit(f"could not read {path}: {e}")
    for entry in args.entry or []:
        lines.extend(entry.splitlines())
    if lines:
        return lines
    if not sys.stdin.isatty():
        return sys.stdin.read().splitlines()

    print("Paste your endpoints, one per line. Blank line (or Ctrl-D) "
          "when done.\n")
    print(BULK_HELP)
    while True:
        try:
            line = input('> ')
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            break
        lines.append(line)
    return lines


def cmd_bulk_add(args) -> int:
    """Add many providers at once, one line each."""
    store = ProviderStore(args.config)
    try:
        lines = _read_bulk_lines(args)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2
    if not lines:
        print("Nothing to add.", file=sys.stderr)
        return 2

    taken = {p.name for p in store.providers}
    existing_by_url = {p.base_url.rstrip('/'): p for p in store.providers}
    parsed: List[Tuple[Provider, set]] = []
    updated: List[str] = []
    errors: List[str] = []
    for i, line in enumerate(lines, 1):
        p, err, provided = parse_bulk_line(line, taken)
        if err:
            errors.append(f"line {i}: {err}")
            continue
        if p is None:
            continue
        # Re-adding a URL we already know updates it in place instead of
        # creating `name-2` duplicates — bulk add is idempotent.
        prior = existing_by_url.get(p.base_url.rstrip('/'))
        if prior is not None and (args.force or 'name' not in provided):
            _merge_into_existing(prior, p, provided)
            updated.append(prior.name)
            continue
        if p.name in taken and not args.force:
            errors.append(f"line {i}: provider '{p.name}' already exists "
                          f"(use --force, or set name=something-else)")
            continue
        taken.add(p.name)
        parsed.append((p, provided))

    for e in errors:
        print(e, file=sys.stderr)
    if not parsed and not updated:
        return 2

    # Show what we understood, then verify against the live endpoints so any
    # line that needs an explicit models= is named before anything is saved.
    all_parsed = [p for p, _ in parsed]
    rows = [[p.name, p.style, p.base_url,
             ('inline' if p.api_key else
              (f'env:{p.api_key_env}' if p.api_key_env else '-')),
             ('auto' if p.autodetect
              else ', '.join(m.tag for m in p.models[:4]) or '(none)'),
             str(len(p.headers))] for p in all_parsed]
    if rows:
        print()
        _print_table(rows, ['NAME', 'STYLE', 'URL', 'KEY', 'MODELS', 'HDRS'])
    if updated:
        print(f"\nUpdated {len(updated)} existing provider(s): "
              f"{', '.join(updated)}")

    results: Dict[str, Tuple[bool, str, List[str]]] = {}
    new_providers = [p for p, _ in parsed]
    if not args.no_verify and new_providers:
        print("\nChecking endpoints...")

        async def run(session):
            out = {}
            for p in new_providers:
                client = ProviderClient(p)
                ok, detail = await client.probe(session)
                found: List[str] = []
                if ok and p.autodetect:
                    found = [m for m in await client.list_models(session)
                             if p.tag_filter_ok(m)]
                out[p.name] = (ok, detail, found)
            return out

        results = asyncio.run(_with_session(run))

    kept, needs_models, unreachable = [], [], []
    for p in new_providers:
        ok, detail, found = results.get(p.name, (True, 'not checked', []))
        has_explicit = bool(p.models)
        # Only bother the operator when the provider can't serve anything:
        # no explicit models AND autodetect couldn't find any.
        if not ok and not has_explicit:
            needs_models.append((p, detail, 'unreachable'))
        elif p.autodetect and not found and not has_explicit:
            needs_models.append((p, detail, 'no-models'))
        elif not ok:
            unreachable.append((p, detail))
        status = ('ok' if (ok or has_explicit) else 'FAILED')
        extra = (f'{len(found)} model(s) detected' if found
                 else (', '.join(m.tag for m in p.models[:4]) if p.models
                       else (detail or 'no models yet')))
        print(f"  [{status:<6}] {p.name:<16} {extra}")
        kept.append(p)

    for p, detail, why in needs_models:
        if why == 'unreachable':
            print(f"\n  ! {p.name} ({p.base_url}) could not be reached "
                  f"({detail}).")
        else:
            print(f"\n  ! {p.name} ({p.base_url}) answered but listed no "
                  f"models, so it can't be autodetected.")
        print(f"    Add models to that line with models=a=model-a,b=model-b "
              f"(or fix the URL). Saved anyway.")
    for p, detail in unreachable:
        print(f"\n  ! {p.name} ({p.base_url}) could not be reached: {detail}")
        print(f"    Saved anyway — fix it with `provider edit {p.name} "
              f"--url ... --ask-key` and it will be picked up automatically.")

    for p in kept:
        store.add(p, overwrite=True)
    store.save()

    added = len(kept)
    verb = 'Added' if added else 'Updated'
    count = added or len(updated)
    print(f"\n{verb} {count} provider(s) to {store.path}")
    print("Next:  python client.py tags     # see what will be advertised")
    print("       python client.py run      # start donating")
    return 0


def _merge_into_existing(existing: Provider, new: Provider,
                         provided: set) -> None:
    """Fold a bulk re-add of the same URL into the stored provider.

    Only fields the operator actually wrote are touched, so re-pasting a URL
    to add a key (or a header, or a model) never wipes what's already there.
    The provider's name is always preserved."""
    if 'key' in provided or 'key-env' in provided:
        existing.api_key = new.api_key
        existing.api_key_env = new.api_key_env
    if 'style' in provided:
        existing.style = new.style
    if 'chat-path' in provided:
        existing.chat_path = new.chat_path
    if 'models-path' in provided:
        existing.models_path = new.models_path
    if 'headers' in provided:
        existing.headers.update(new.headers)
    if 'models' in provided:
        existing.models = new.models
        existing.autodetect = new.autodetect
    elif not existing.models:
        # They didn't give models; keep autodetect on (nothing else can serve).
        existing.autodetect = existing.models_url() is not None
    # A URL re-add that only changes the key leaves everything else alone.


async def _with_session(coro):
    async with aiohttp.ClientSession() as session:
        return await coro(session)


# ── commands ────────────────────────────────────────────────────────────────
def cmd_presets(args) -> int:
    rows = []
    for name in sorted(PRESETS):
        spec = PRESETS[name]
        rows.append([
            name,
            spec.get('base_url') or '(you supply)',
            spec.get('style', 'openai'),
            'yes' if spec.get('needs_key', True) else 'no',
            'yes' if spec.get('autodetect') else 'no',
            spec.get('desc', ''),
        ])
    _print_table(rows, ['PRESET', 'DEFAULT URL', 'STYLE', 'KEY', 'DETECT',
                        'DESCRIPTION'])
    print("\nAdd one with:  provider add <name> --preset <preset> "
          "[--url ...] [--key-env VAR]")
    return 0


def _apply_common(p: Provider, args, store: ProviderStore) -> None:
    """Apply the shared add/edit flags onto a provider."""
    if getattr(args, 'url', None):
        p.base_url = args.url.rstrip('/')
    if getattr(args, 'style', None):
        p.style = args.style
    if getattr(args, 'chat_path', None) is not None:
        p.chat_path = args.chat_path
    if getattr(args, 'models_path', None) is not None:
        p.models_path = args.models_path
    if getattr(args, 'auth', None):
        p.auth = args.auth
    if getattr(args, 'auth_param', None):
        p.auth_param = args.auth_param
    if getattr(args, 'key_env', None):
        p.api_key_env = args.key_env
        p.api_key = ''
    if getattr(args, 'timeout', None):
        p.timeout = int(args.timeout)
    if getattr(args, 'header', None):
        headers = _parse_headers(args.header)
        if getattr(args, 'replace_headers', False):
            p.headers = headers
        else:
            p.headers.update(headers)
    if getattr(args, 'clear_headers', False):
        p.headers = {}
    if getattr(args, 'extra_body', None):
        p.extra_body = _parse_json_obj(args.extra_body, '--extra-body')
    if getattr(args, 'include', None):
        p.include = _csv(args.include)
    if getattr(args, 'exclude', None):
        p.exclude = _csv(args.exclude)
    if getattr(args, 'autodetect', False):
        p.autodetect = True
    if getattr(args, 'no_autodetect', False):
        p.autodetect = False
    if getattr(args, 'qualify', False):
        p.qualify = True
    if getattr(args, 'no_qualify', False):
        p.qualify = False
    maps = _parse_maps(getattr(args, 'map', None))
    if maps:
        if getattr(args, 'replace_maps', False):
            p.models = maps
        else:
            by_tag = {m.tag: m for m in p.models}
            for m in maps:
                by_tag[m.tag] = m
            p.models = list(by_tag.values())
    if getattr(args, 'clear_maps', False):
        p.models = []


def cmd_add(args) -> int:
    store = ProviderStore(args.config)
    preset = args.preset or 'custom'
    if preset not in PRESETS:
        print(f"unknown preset {preset!r}; see `provider presets`",
              file=sys.stderr)
        return 2
    if store.get(args.name) is not None and not args.force:
        # Fail before prompting for a key we would only throw away.
        print(f"provider '{args.name}' already exists "
              f"(use `provider edit` or --force)", file=sys.stderr)
        return 2
    p = Provider.from_preset(args.name, preset)
    _apply_common(p, args, store)

    if not p.base_url:
        print(f"provider '{args.name}': no URL. Pass --url "
              f"(preset '{preset}' has no default).", file=sys.stderr)
        return 2

    # API key: --key > --key-env > interactive prompt (skippable).
    if args.key:
        p.api_key = args.key
    elif args.key_stdin:
        p.api_key = sys.stdin.readline().strip()
    elif not p.api_key_env and not args.no_key:
        if preset_needs_key(preset) or args.ask_key:
            p.api_key = _prompt_key(args.name, preset)

    if not p.models and not p.autodetect:
        # Nothing would be advertised — pick the safer default explicitly
        # instead of silently registering a provider that serves nothing.
        print(f"provider '{args.name}': no --map given, enabling "
              f"--autodetect so its models are discovered.")
        p.autodetect = True
    if p.autodetect and p.models_url() is None:
        # No listing endpoint to detect from; only explicit maps can work.
        p.autodetect = False
        if not p.models:
            print(f"provider '{args.name}': this endpoint has no model "
                  f"listing, so nothing is advertised yet. Map a tag:\n"
                  f"  python client.py provider map {args.name} "
                  f"mytag=upstream-model", file=sys.stderr)

    try:
        store.add(p, overwrite=args.force)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    store.save()
    print(f"Added provider '{p.name}' ({p.style} @ {p.base_url})")
    print(f"  config: {store.path}")
    if p.models:
        for m in p.models:
            print(f"  tag {m.tag} -> {m.model}")
    if p.autodetect:
        print("  autodetect: on (run `provider models "
              f"{p.name}` to see what it finds)")
    return 0


def cmd_edit(args) -> int:
    store = ProviderStore(args.config)
    p = store.get(args.name)
    if p is None:
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2
    _apply_common(p, args, store)
    if args.key:
        p.api_key = args.key
    elif args.key_stdin:
        p.api_key = sys.stdin.readline().strip()
    elif args.ask_key:
        p.api_key = _prompt_key(p.name, p.preset)
    if args.rename:
        if store.get(args.rename) is not None:
            print(f"provider '{args.rename}' already exists", file=sys.stderr)
            return 2
        p.name = args.rename
    store.save()
    print(f"Updated provider '{p.name}'")
    return 0


def cmd_remove(args) -> int:
    store = ProviderStore(args.config)
    if not store.remove(args.name):
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2
    store.save()
    print(f"Removed provider '{args.name}'")
    return 0


def cmd_enable(args, enabled: bool) -> int:
    store = ProviderStore(args.config)
    p = store.get(args.name)
    if p is None:
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2
    p.enabled = enabled
    store.save()
    print(f"Provider '{p.name}' {'enabled' if enabled else 'disabled'}")
    return 0


def cmd_list(args) -> int:
    store = ProviderStore(args.config)
    if args.json:
        print(json.dumps([p.redacted() for p in store.providers], indent=2))
        return 0
    if not store.providers:
        print(f"No providers configured ({store.path}).")
        print("Add one:  provider add openai --preset openai")
        print("      or:  provider add mygw --url https://gw.example.com "
              "--map fast=some-model")
        return 0
    rows = []
    for p in store.providers:
        key = 'inline' if p.api_key else (f'env:{p.api_key_env}'
                                          if p.api_key_env else '-')
        rows.append([
            p.name,
            'on' if p.enabled else 'off',
            p.style,
            p.base_url,
            key,
            'yes' if p.autodetect else 'no',
            str(len(p.models)),
            str(len(p.headers)),
        ])
    _print_table(rows, ['NAME', 'STATE', 'STYLE', 'URL', 'KEY', 'DETECT',
                        'MAPS', 'HDRS'])
    print(f"\nconfig: {store.path}")
    return 0


def cmd_show(args) -> int:
    store = ProviderStore(args.config)
    p = store.get(args.name)
    if p is None:
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2
    print(json.dumps(p.redacted(), indent=2))
    return 0


def cmd_map(args) -> int:
    """Point a tag at a specific model on a provider."""
    store = ProviderStore(args.config)
    p = store.get(args.name)
    if p is None:
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2
    maps = _parse_maps(args.mapping)
    if not maps:
        print("nothing to map; pass tag=model", file=sys.stderr)
        return 2
    by_tag = {m.tag: m for m in p.models}
    for m in maps:
        by_tag[m.tag] = m
        print(f"tag {m.tag} -> {p.name}:{m.model}")
    p.models = list(by_tag.values())
    store.save()
    return 0


def cmd_unmap(args) -> int:
    store = ProviderStore(args.config)
    p = store.get(args.name)
    if p is None:
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2
    before = len(p.models)
    p.models = [m for m in p.models if m.tag not in set(args.tag)]
    store.save()
    print(f"Removed {before - len(p.models)} mapping(s) from '{p.name}'")
    return 0


def cmd_models(args) -> int:
    """Autodetect: ask the provider what models it hosts."""
    store = ProviderStore(args.config)
    p = store.get(args.name)
    if p is None:
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2

    async def run(session):
        return await ProviderClient(p).list_models(session)

    models = asyncio.run(_with_session(run))
    if not models:
        url = p.models_url()
        print(f"No models detected for '{p.name}'"
              + (f" via {url}" if url else " (no listing endpoint configured)"))
        print("Map tags manually:  provider map "
              f"{p.name} mytag=upstream-model")
        return 1
    shown = [m for m in models if p.tag_filter_ok(m)]
    for m in shown:
        print(m)
    hidden = len(models) - len(shown)
    print(f"\n{len(shown)} model(s)"
          + (f", {hidden} filtered by include/exclude" if hidden else ''),
          file=sys.stderr)
    if args.map_all:
        p.models = [ModelMap(m, m) for m in shown]
        p.autodetect = False
        store.save()
        print(f"Pinned {len(shown)} tag(s) onto '{p.name}' "
              f"(autodetect turned off)", file=sys.stderr)
    elif args.enable_autodetect and not p.autodetect:
        p.autodetect = True
        store.save()
        print(f"Autodetect enabled for '{p.name}'", file=sys.stderr)
    return 0


def cmd_test(args) -> int:
    store = ProviderStore(args.config)
    targets = ([store.get(args.name)] if args.name
               else list(store.providers))
    if args.name and targets[0] is None:
        print(f"no such provider: {args.name}", file=sys.stderr)
        return 2
    if not targets:
        print("no providers configured", file=sys.stderr)
        return 2

    async def run(session):
        results = []
        for p in targets:
            ok, detail = await ProviderClient(p).probe(session)
            results.append((p, ok, detail))
            if ok and args.prompt:
                try:
                    model = (p.models[0].model if p.models else None)
                    if model is None:
                        ids = await ProviderClient(p).list_models(session)
                        model = ids[0] if ids else None
                    if model is None:
                        results[-1] = (p, ok, detail + '; no model to prompt')
                        continue
                    out = await ProviderClient(p).generate(
                        session, model, args.prompt, {'num_predict': 64})
                    text = (out.get('response') or '').strip()
                    results[-1] = (p, True,
                                   f'{model}: {text[:120]!r}')
                except Exception as e:                # noqa: BLE001 - report
                    results[-1] = (p, False, f'generate failed: {e}')
        return results

    results = asyncio.run(_with_session(run))
    failed = 0
    for p, ok, detail in results:
        mark = 'ok  ' if ok else 'FAIL'
        print(f"[{mark}] {p.name:<16} {p.base_url}  {detail}")
        failed += 0 if ok else 1
    return 1 if failed else 0


def cmd_tags(args) -> int:
    """Show the tag -> provider:model table the worker would advertise."""
    store = ProviderStore(args.config)
    providers = store.enabled_providers()
    if not providers:
        print(f"No enabled providers ({store.path})", file=sys.stderr)
        return 1

    async def run(session):
        return await ModelRegistry().build(providers, session)

    reg = asyncio.run(_with_session(run))
    rows = [[t, pn, m] for t, pn, m in reg.describe()]
    if args.json:
        print(json.dumps([{'tag': t, 'provider': pn, 'model': m}
                          for t, pn, m in rows], indent=2))
        return 0
    if not rows:
        print("No tags resolved — map some models or enable autodetect.",
              file=sys.stderr)
        return 1
    _print_table(rows, ['TAG', 'PROVIDER', 'UPSTREAM MODEL'])
    print(f"\n{len(rows)} tag(s) would be advertised to the coordinator.")
    return 0


def cmd_wizard(args) -> int:
    """Interactive add — for people who would rather not read flags."""
    store = ProviderStore(args.config)
    print("Platinum provider setup")
    print(f"config: {store.path}\n")
    print("Presets: " + ', '.join(sorted(PRESETS)))
    preset = input("preset [custom]: ").strip() or 'custom'
    if preset not in PRESETS:
        print(f"unknown preset {preset!r}", file=sys.stderr)
        return 2
    default_name = preset if store.get(preset) is None else ''
    name = input(f"provider name [{default_name or 'required'}]: ").strip() \
        or default_name
    if not name:
        print("a name is required", file=sys.stderr)
        return 2
    spec = PRESETS[preset]
    default_url = spec.get('base_url', '')
    url = input(f"base URL [{default_url or 'required'}]: ").strip() \
        or default_url
    if not url:
        print("a URL is required", file=sys.stderr)
        return 2
    p = Provider.from_preset(name, preset)
    p.base_url = url.rstrip('/')
    style = input(f"API style {STYLES} [{p.style}]: ").strip()
    if style:
        if style not in STYLES:
            print(f"unknown style {style!r}", file=sys.stderr)
            return 2
        p.style = style
    key = _prompt_key(name, preset)
    if key:
        p.api_key = key
    while True:
        h = input("extra header 'Name: value' (blank to finish): ").strip()
        if not h:
            break
        try:
            p.headers.update(_parse_headers([h]))
        except SystemExit as e:
            print(e)
    detect = input("autodetect models from the endpoint? [Y/n]: ").strip().lower()
    p.autodetect = detect not in ('n', 'no')
    maps = input("tag mappings, e.g. 'fast=gpt-4o-mini,smart=o3' (blank = none): ").strip()
    if maps:
        p.models = _parse_maps([maps])
    if not p.autodetect and not p.models:
        print("nothing would be advertised; enabling autodetect")
        p.autodetect = True
    try:
        store.add(p, overwrite=True)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    store.save()
    print(f"\nSaved provider '{p.name}'.")

    async def run(session):
        return await ProviderClient(p).probe(session)

    ok, detail = asyncio.run(_with_session(run))
    print(f"connectivity: {'ok' if ok else 'FAILED'} — {detail}")
    print("\nNext:  python client.py tags     # see what will be advertised")
    print("       python client.py run      # start donating")
    return 0


def cmd_config_path(args) -> int:
    print(ProviderStore(args.config).path)
    return 0


# ── parser wiring ───────────────────────────────────────────────────────────
def _add_bulk_flags(sp) -> None:
    sp.add_argument('entry', nargs='*',
                    help="One endpoint per argument, e.g. "
                         "'https://api.deepseek.com sk-abc models=fast=chat'")
    sp.add_argument('--file', action='append', metavar='FILE',
                    help='Read endpoints from a file (one per line, - = stdin)')
    sp.add_argument('--force', action='store_true',
                    help='Overwrite any existing provider with the same name')
    sp.add_argument('--no-verify', action='store_true',
                    help="Don't contact the endpoints; just save them")


def _add_provider_flags(sp, editing: bool) -> None:
    sp.add_argument('--url', help='Base URL of the provider')
    sp.add_argument('--style', choices=list(STYLES),
                    help='API style (default from preset: openai)')
    sp.add_argument('--chat-path',
                    help="Override the generation path (e.g. '/chat/completions')")
    sp.add_argument('--models-path',
                    help="Override the model-listing path; '-' means the "
                         "provider has none")
    sp.add_argument('--auth', choices=['auto', 'bearer', 'x-api-key', 'query',
                                       'none'],
                    help='How to send the API key (default: auto)')
    sp.add_argument('--auth-param',
                    help="Query parameter name when --auth query (default: key)")
    sp.add_argument('--key', help='API key (stored in the 0600 config file)')
    sp.add_argument('--key-env', help='Read the API key from this env var '
                                      'instead of storing it')
    sp.add_argument('--key-stdin', action='store_true',
                    help='Read the API key from stdin')
    sp.add_argument('--header', action='append', metavar='NAME: VALUE',
                    help="Extra header, repeatable. '{api_key}' is substituted")
    sp.add_argument('--replace-headers', action='store_true',
                    help='Replace instead of merging existing headers')
    sp.add_argument('--clear-headers', action='store_true',
                    help='Drop all custom headers')
    sp.add_argument('--map', action='append', metavar='TAG=MODEL',
                    help='Advertise TAG, routed to MODEL on this provider')
    sp.add_argument('--replace-maps', action='store_true',
                    help='Replace instead of merging existing tag mappings')
    sp.add_argument('--clear-maps', action='store_true',
                    help='Drop all tag mappings')
    sp.add_argument('--autodetect', action='store_true',
                    help='Advertise every model the endpoint reports')
    sp.add_argument('--no-autodetect', action='store_true',
                    help='Only advertise explicit --map tags')
    sp.add_argument('--include', help='Comma-separated glob allow-list applied '
                                      'to autodetected model ids')
    sp.add_argument('--exclude', help='Comma-separated glob deny-list applied '
                                      'to autodetected model ids')
    sp.add_argument('--qualify', action='store_true',
                    help="Also advertise '<provider>/<model>' aliases (default)")
    sp.add_argument('--no-qualify', action='store_true',
                    help="Don't advertise '<provider>/<model>' aliases")
    sp.add_argument('--timeout', type=int,
                    help='Per-request timeout in seconds (default 300)')
    sp.add_argument('--extra-body', metavar='JSON',
                    help='JSON object merged into every request body')
    sp.add_argument('--ask-key', action='store_true',
                    help='Prompt for the API key (hidden input)')
    if not editing:
        sp.add_argument('--no-key', action='store_true',
                        help='Skip the API key prompt entirely')
        sp.add_argument('--force', action='store_true',
                        help='Overwrite an existing provider with this name')
        sp.add_argument('--preset', help='Start from a preset '
                                         '(see `provider presets`)')
    else:
        sp.add_argument('--rename', help='New name for this provider')


def build_cli_parser(argparse_mod, config_default: Optional[str] = None):
    """Build the management CLI (everything except `run`)."""
    ap = argparse_mod.ArgumentParser(
        prog='client.py',
        description='EditorAI Platinum worker — provider management',
        formatter_class=argparse_mod.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # a preset (still needs your key)
  python client.py provider add deepseek --preset deepseek --autodetect

  # any endpoint you like, with custom headers and hand-picked tags
  python client.py provider add mygw --url https://gw.example.com/v1 \\
      --header 'X-Org: acme' --header 'X-Trace: on' \\
      --map fast=llama-3.1-8b --map smart=llama-3.1-70b

  # let the worker discover everything the endpoint hosts
  python client.py provider add router --preset openrouter --autodetect \\
      --include 'meta-llama/*,qwen/*'

  # inspect and start
  python client.py tags
  python client.py run
""")
    ap.add_argument('--config', default=config_default,
                    help=f'Provider config file (default: {default_config_path()})')
    sub = ap.add_subparsers(dest='cmd')

    prov = sub.add_parser('provider', help='Manage providers')
    psub = prov.add_subparsers(dest='subcmd')

    sp = psub.add_parser('add', help='Add a provider')
    sp.add_argument('name')
    _add_provider_flags(sp, editing=False)
    sp.set_defaults(func=cmd_add)

    sp = psub.add_parser('edit', help='Change an existing provider')
    sp.add_argument('name')
    _add_provider_flags(sp, editing=True)
    sp.set_defaults(func=cmd_edit)

    sp = psub.add_parser('remove', aliases=['rm'], help='Delete a provider')
    sp.add_argument('name')
    sp.set_defaults(func=cmd_remove)

    sp = psub.add_parser('list', aliases=['ls'], help='List providers')
    sp.add_argument('--json', action='store_true')
    sp.set_defaults(func=cmd_list)

    sp = psub.add_parser('show', help='Show one provider (key redacted)')
    sp.add_argument('name')
    sp.set_defaults(func=cmd_show)

    sp = psub.add_parser('enable', help='Enable a provider')
    sp.add_argument('name')
    sp.set_defaults(func=lambda a: cmd_enable(a, True))

    sp = psub.add_parser('disable', help='Disable a provider')
    sp.add_argument('name')
    sp.set_defaults(func=lambda a: cmd_enable(a, False))

    sp = psub.add_parser('map', help='Point tags at models on a provider')
    sp.add_argument('name')
    sp.add_argument('mapping', nargs='+', metavar='TAG=MODEL')
    sp.set_defaults(func=cmd_map)

    sp = psub.add_parser('unmap', help='Remove tag mappings')
    sp.add_argument('name')
    sp.add_argument('tag', nargs='+')
    sp.set_defaults(func=cmd_unmap)

    sp = psub.add_parser('models', help='Autodetect models on a provider')
    sp.add_argument('name')
    sp.add_argument('--map-all', action='store_true',
                    help='Pin every detected model as a tag')
    sp.add_argument('--enable-autodetect', action='store_true',
                    help='Turn autodetect on for this provider')
    sp.set_defaults(func=cmd_models)

    sp = psub.add_parser('test', help='Check connectivity / auth')
    sp.add_argument('name', nargs='?')
    sp.add_argument('--prompt', help='Also run this prompt through it')
    sp.set_defaults(func=cmd_test)

    sp = psub.add_parser('presets', help='List built-in presets')
    sp.set_defaults(func=cmd_presets)

    sp = psub.add_parser('wizard', help='Interactive provider setup')
    sp.set_defaults(func=cmd_wizard)

    # Bulk-add under `provider` too, for discoverability.
    sp = psub.add_parser('add-many', aliases=['bulk', 'import'],
                         help='Add many endpoints at once (one per line)',
                         formatter_class=argparse_mod.RawDescriptionHelpFormatter,
                         description=BULK_HELP)
    _add_bulk_flags(sp)
    sp.set_defaults(func=cmd_bulk_add)

    # Top-level conveniences.
    sp = sub.add_parser('add', aliases=['bulk', 'import', 'add-many'],
                        help='Add many endpoints at once (one per line)',
                        formatter_class=argparse_mod.RawDescriptionHelpFormatter,
                        description=BULK_HELP)
    _add_bulk_flags(sp)
    sp.set_defaults(func=cmd_bulk_add)

    sp = sub.add_parser('tags', help='Show the tags that would be advertised')
    sp.add_argument('--json', action='store_true')
    sp.set_defaults(func=cmd_tags)

    sp = sub.add_parser('presets', help='List built-in presets')
    sp.set_defaults(func=cmd_presets)

    sp = sub.add_parser('wizard', help='Interactive provider setup')
    sp.set_defaults(func=cmd_wizard)

    sp = sub.add_parser('config-path', help='Print the config file path')
    sp.set_defaults(func=cmd_config_path)

    return ap, prov


def run_cli(argv: List[str]) -> int:
    import argparse
    ap, prov = build_cli_parser(argparse)
    args = ap.parse_args(argv)
    func = getattr(args, 'func', None)
    if func is None:
        (prov if args.cmd == 'provider' else ap).print_help()
        return 2
    try:
        return func(args)
    except RuntimeError as e:
        # Unreadable / corrupt config: a one-line message beats a traceback.
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


# ════════════════════════════════════════════════════════════════════════════
# Worker
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class SystemResources:
    total_ram_gb: float
    available_ram_gb: float
    total_vram_gb: float
    available_vram_gb: float
    total_disk_gb: float
    available_disk_gb: float
    cpu_count: int
    gpu_name: Optional[str] = None


class PlatinumWorker:
    """Polls the coordinator for work and runs it on the configured providers.

    Compat note: the old constructor signature
    (coordinator_url, backend, endpoint, api_key, models, worker_id) is still
    accepted and is translated into a single synthetic provider, so any script
    that imported this class keeps working.
    """

    def __init__(
        self,
        coordinator_url: str,
        backend: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        models: Optional[List[str]] = None,
        worker_id: Optional[str] = None,
        providers: Optional[List[Provider]] = None,
        config_path: Optional[str] = None,
        reload_interval: float = 5.0,
        poll_interval: float = 2.0,
        concurrency: int = 1,
    ):
        self.coordinator_url = coordinator_url.rstrip('/')
        self.worker_id = worker_id or str(uuid.uuid4())
        self.is_running = False
        self.config_path = config_path
        self.reload_interval = max(0.0, reload_interval)
        self.poll_interval = max(0.25, poll_interval)
        self.concurrency = max(1, int(concurrency))
        self._active = 0
        self._config_mtime: Optional[float] = None
        self.registry = ModelRegistry()
        self._advertised: List[str] = []
        self._session: Optional[aiohttp.ClientSession] = None

        if providers is not None:
            self.providers = list(providers)
        elif backend is not None or endpoint or models or api_key:
            self.providers = [legacy_provider(backend or 'ollama', endpoint,
                                              api_key, models)]
        else:
            self.providers = []

        # Legacy attributes some scripts read.
        self.backend = backend or (self.providers[0].preset
                                   if self.providers else 'multi')
        self.endpoint = self.providers[0].base_url if self.providers else ''
        self.api_key = api_key or ''
        self.configured_models = list(models or [])

    # ── Resource probing ────────────────────────────────────────────────────
    def get_gpu_info(self):
        try:
            result = subprocess.run(
                ['nvidia-smi',
                 '--query-gpu=name,memory.total,memory.free',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if lines:
                    parts = lines[0].split(',')
                    return (parts[0].strip(),
                            float(parts[1].strip()) / 1024,
                            float(parts[2].strip()) / 1024)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"Could not get GPU info: {e}")
        return None, 0.0, 0.0

    def get_system_resources(self) -> SystemResources:
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        gpu_name, total_vram_gb, available_vram_gb = self.get_gpu_info()
        return SystemResources(
            total_ram_gb=ram.total / (1024**3),
            available_ram_gb=ram.available / (1024**3),
            total_vram_gb=total_vram_gb,
            available_vram_gb=available_vram_gb,
            total_disk_gb=disk.total / (1024**3),
            available_disk_gb=disk.free / (1024**3),
            cpu_count=psutil.cpu_count(logical=False) or 1,
            gpu_name=gpu_name,
        )

    # ── Session / registry ─────────────────────────────────────────────────
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def refresh_registry(self) -> List[str]:
        """Rebuild the tag routing table from the enabled providers."""
        enabled = [p for p in self.providers if p.enabled]
        self.registry = await ModelRegistry().build(enabled, self.session())
        return self.registry.tags()

    async def get_models(self) -> List[str]:
        """Tags this worker can serve (kept for API compatibility)."""
        return await self.refresh_registry()

    # ── Coordinator registration / heartbeat ───────────────────────────────
    async def register_with_coordinator(self) -> bool:
        try:
            resources = self.get_system_resources()
            models = await self.refresh_registry()
            if not models:
                self._explain_no_models()
                return False

            registration_data = {
                'worker_id': self.worker_id,
                # PRIVACY: never send the real IP. The coordinator only ever
                # hashes address:port for its status page and never dials the
                # worker back (pull model), so a constant placeholder is fine.
                'address': 'hidden',
                'port': 0,
                'resources': {
                    'total_ram_gb': resources.total_ram_gb,
                    'available_ram_gb': resources.available_ram_gb,
                    'total_vram_gb': resources.total_vram_gb,
                    'available_vram_gb': resources.available_vram_gb,
                    'total_disk_gb': resources.total_disk_gb,
                    'available_disk_gb': resources.available_disk_gb,
                    'cpu_count': resources.cpu_count,
                    'gpu_name': resources.gpu_name,
                },
                'models': models,
            }
            url = f"{self.coordinator_url}/api/workers/register"
            async with self.session().post(
                    url, json=registration_data,
                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    self._advertised = models
                    logger.info("Registered with coordinator "
                                f"({len(self.providers)} provider(s))")
                    logger.info(f"Worker ID: {self.worker_id}")
                    logger.info(f"Serving tags: {', '.join(models[:8])}"
                                f"{'...' if len(models) > 8 else ''}"
                                f" ({len(models)} total)")
                    return True
                logger.error(f"Register failed: HTTP {r.status} - "
                             f"{await r.text()}")
        except Exception as e:
            logger.error(f"Error registering with coordinator: {e}")
        return False

    async def send_heartbeat(self):
        while self.is_running:
            try:
                resources = self.get_system_resources()
                data = {
                    'worker_id': self.worker_id,
                    'status': 'busy' if self._active else 'idle',
                    'resources': {
                        'available_ram_gb': resources.available_ram_gb,
                        'available_vram_gb': resources.available_vram_gb,
                        'available_disk_gb': resources.available_disk_gb,
                    },
                }
                url = f"{self.coordinator_url}/api/workers/heartbeat"
                async with self.session().post(
                        url, json=data,
                        timeout=aiohttp.ClientTimeout(total=10)) as r:
                    # SELF-HEAL: a 404 means the coordinator restarted and
                    # no longer knows us. Re-register instead of heart-
                    # beating into the void forever.
                    if r.status == 404:
                        logger.info("Coordinator forgot us (restarted?) - "
                                    "re-registering...")
                        await self.register_with_coordinator()
                    elif r.status != 200:
                        logger.warning(f"Heartbeat HTTP {r.status}")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(10)

    # ── Hot reload ─────────────────────────────────────────────────────────
    def _config_stamp(self) -> Optional[float]:
        if not self.config_path:
            return None
        try:
            return os.stat(self.config_path).st_mtime
        except OSError:
            return None

    async def watch_config(self):
        """Pick up provider changes without a restart.

        The CLI writes the config atomically (os.replace), so an mtime change
        always means a complete file. On change we rebuild the registry and,
        if the advertised tag set moved, re-register with the coordinator —
        which is exactly how a fresh worker announces itself, so nothing on
        the coordinator or client side has to know about reloads."""
        if not self.config_path or not self.reload_interval:
            return
        self._config_mtime = self._config_stamp()
        while self.is_running:
            await asyncio.sleep(self.reload_interval)
            stamp = self._config_stamp()
            if stamp is None or stamp == self._config_mtime:
                continue
            self._config_mtime = stamp
            logger.info(f"Provider config changed ({self.config_path}) - "
                        "reloading")
            try:
                store = ProviderStore(self.config_path)
            except RuntimeError as e:
                logger.error(f"Reload failed, keeping current providers: {e}")
                continue
            if not store.providers:
                logger.warning("Reloaded config has no providers - keeping "
                               "the previous set")
                continue
            self.providers = store.providers
            before = set(self._advertised)
            try:
                tags = await self.refresh_registry()
            except Exception as e:
                logger.error(f"Reload: registry rebuild failed: {e}")
                continue
            if not tags:
                logger.warning("Reloaded config advertises no tags - keeping "
                               "the previous registration")
                continue
            if set(tags) != before:
                added = sorted(set(tags) - before)
                gone = sorted(before - set(tags))
                if added:
                    logger.info(f"  + {len(added)} tag(s): "
                                f"{', '.join(added[:8])}"
                                f"{'...' if len(added) > 8 else ''}")
                if gone:
                    logger.info(f"  - {len(gone)} tag(s): "
                                f"{', '.join(gone[:8])}"
                                f"{'...' if len(gone) > 8 else ''}")
                await self.register_with_coordinator()
            else:
                logger.info("  provider details changed; tag list unchanged")

    # ── Work loop ──────────────────────────────────────────────────────────
    async def poll_for_work(self):
        while self.is_running:
            try:
                if self._active >= self.concurrency:
                    await asyncio.sleep(0.25)
                    continue
                url = f"{self.coordinator_url}/api/work?worker_id={self.worker_id}"
                async with self.session().get(
                        url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        work = await r.json()
                        if work.get('request_id'):
                            logger.info(f"Received work: {work['request_id']}")
                            if self.concurrency > 1:
                                asyncio.create_task(
                                    self._process_tracked(work['request_id'],
                                                          work))
                            else:
                                await self._process_tracked(
                                    work['request_id'], work)
                        else:
                            await asyncio.sleep(self.poll_interval)
                    elif r.status in (400, 404):
                        # Unknown worker_id — coordinator restarted.
                        logger.info("Coordinator doesn't know this worker "
                                    "- re-registering...")
                        await self.register_with_coordinator()
                        await asyncio.sleep(3)
                    else:
                        logger.warning(f"Get work HTTP {r.status}")
                        await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Poll error: {e}")
                await asyncio.sleep(5)

    async def _process_tracked(self, request_id: str, work: dict):
        self._active += 1
        try:
            await self.process_work(request_id, work)
        finally:
            self._active -= 1

    async def process_work(self, request_id: str, work: dict):
        tag = work.get('model')
        prompt = work.get('prompt')
        options = work.get('options', {})
        route = self.registry.resolve(tag or '')
        if route is None:
            # The coordinator handed us a tag we no longer serve (config was
            # reloaded mid-flight). Report it so the fallback chain moves on
            # instead of the request stalling until its deadline.
            logger.warning(f"{request_id}: no provider serves tag {tag!r}")
            await self.submit_error(request_id,
                                    f"worker no longer serves model '{tag}'")
            return
        logger.info(f"Processing {request_id}: {tag} -> "
                    f"{route.provider.name}:{route.model}")
        started = time.monotonic()
        try:
            result = await route.client.generate(self.session(), route.model,
                                                 prompt, options)
            # Answer under the tag the network asked for, not the upstream
            # name — clients match on what they requested.
            if isinstance(result, dict):
                result.setdefault('done', True)
                result['model'] = tag or result.get('model') or route.model
            took = time.monotonic() - started
            logger.info(f"{request_id}: done in {took:.1f}s via "
                        f"{route.provider.name}")
            await self.submit_result(request_id, result)
        except asyncio.TimeoutError:
            await self.submit_error(
                request_id,
                f"timeout after {route.provider.timeout}s on "
                f"{route.provider.name}")
        except Exception as e:
            logger.error(f"Error on {request_id}: {e}")
            await self.submit_error(request_id, str(e))

    async def submit_result(self, request_id: str, result: dict):
        try:
            url = f"{self.coordinator_url}/api/result/{request_id}"
            async with self.session().post(
                    url, json={'worker_id': self.worker_id, 'result': result},
                    timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    logger.info(f"Submitted result for {request_id}")
                else:
                    logger.error(f"Submit result HTTP {r.status}")
        except Exception as e:
            logger.error(f"Error submitting result: {e}")

    async def submit_error(self, request_id: str, error: str):
        try:
            url = f"{self.coordinator_url}/api/result/{request_id}"
            async with self.session().post(
                    url, json={'worker_id': self.worker_id, 'error': error},
                    timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    logger.error(f"Submit error HTTP {r.status}")
        except Exception as e:
            logger.error(f"Error submitting error: {e}")

    def _explain_no_models(self) -> None:
        """Tell the donor what to do, in the terms of how they invoked us.

        The old client's message for a bare `python client.py` was about the
        local Ollama server; keep that, and only mention provider config when
        provider config is actually what's in play."""
        local = [p for p in self.providers
                 if p.enabled and p.preset in ('ollama', 'llamacpp',
                                               'lmstudio', 'vllm')]
        remote = [p for p in self.providers
                  if p.enabled and p not in local]
        logger.error("No models to serve.")
        for p in local:
            logger.error(f"  {p.preset} at {p.base_url} reported no models - "
                         f"start it and pull/load a model.")
        for p in remote:
            if not p.models and not p.autodetect:
                logger.error(f"  {p.name}: no models listed. Pass --models, "
                             f"or map tags: `provider map {p.name} "
                             f"tag=model`.")
            else:
                logger.error(f"  {p.name}: endpoint returned no usable models "
                             f"(check the API key, URL and any "
                             f"include/exclude filters).")

    async def probe_providers(self) -> int:
        """Log reachability for each provider; return how many answered."""
        ok_count = 0
        for p in self.providers:
            if not p.enabled:
                logger.info(f"  {p.name}: disabled")
                continue
            ok, detail = await ProviderClient(p).probe(self.session())
            level = logger.info if ok else logger.warning
            level(f"  {p.name} ({p.style} @ {p.base_url}): "
                  f"{'ok' if ok else 'unreachable'} - {detail}")
            if ok:
                ok_count += 1
            elif p.preset in ('ollama', 'llamacpp', 'lmstudio', 'vllm'):
                # Same guidance the old single-backend client gave when a
                # local server wasn't up — the most common donor mistake.
                logger.error(f"{p.name} not reachable at {p.base_url}")
                logger.error("Start the server and retry.")
        return ok_count

    async def start(self):
        logger.info("=" * 60)
        logger.info("EditorAI Platinum Worker")
        logger.info("=" * 60)
        logger.info(f"Worker ID:   {self.worker_id}")
        logger.info(f"Coordinator: {self.coordinator_url}")
        if self.config_path:
            logger.info(f"Config:      {self.config_path}")
        logger.info(f"Providers:   {len(self.providers)}")
        logger.info("=" * 60)

        if not self.providers:
            logger.error("No providers configured.")
            logger.error("Add one, e.g.:")
            logger.error("  python client.py provider add ollama "
                         "--preset ollama")
            logger.error("  python client.py provider add deepseek "
                         "--preset deepseek --autodetect")
            logger.error("  python client.py provider wizard")
            await self.close()
            return

        logger.info("Checking providers...")
        reachable = await self.probe_providers()
        # COMPAT: the old client probed the backend and exited before ever
        # contacting the coordinator when it was down. Keep that, but only
        # when nothing could be advertised anyway — a provider with explicit
        # tag maps is still usable even if its listing endpoint refuses us.
        if not reachable and not any(p.models for p in self.providers
                                     if p.enabled):
            self._explain_no_models()
            await self.close()
            return

        logger.info("Registering with coordinator...")
        if not await self.register_with_coordinator():
            logger.error("Registration failed. Exiting.")
            await self.close()
            return

        self.is_running = True
        tasks = [
            asyncio.create_task(self.send_heartbeat()),
            asyncio.create_task(self.poll_for_work()),
        ]
        if self.config_path and self.reload_interval:
            tasks.append(asyncio.create_task(self.watch_config()))
            logger.info(f"Hot reload on: edit providers while running "
                        f"(checked every {self.reload_interval:g}s)")
        logger.info("=" * 60)
        logger.info("Worker active - donating compute to the network!")
        logger.info("Press Ctrl+C to stop.")
        logger.info("=" * 60)
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutting down worker...")
        finally:
            self.is_running = False
            for t in tasks:
                t.cancel()
            await self.close()
            logger.info("Worker stopped. Thank you for contributing!")

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()


# ── Legacy compatibility ────────────────────────────────────────────────────
def legacy_provider(backend: str, endpoint: Optional[str],
                    api_key: Optional[str],
                    models: Optional[List[str]]) -> Provider:
    """Translate the old --backend/--endpoint/--models flags into a provider.

    The resulting worker behaves exactly like the previous single-backend
    client: ollama/llamacpp autodetect their models unless --models is given,
    and openai requires --models. Qualified aliases are off so the advertised
    tag list is byte-for-byte what old workers announced."""
    if backend == 'ollama':
        p = Provider.from_preset('ollama', 'ollama')
        p.base_url = (endpoint or 'http://localhost:11434').rstrip('/')
    elif backend == 'llamacpp':
        p = Provider.from_preset('llamacpp', 'llamacpp')
        p.base_url = (endpoint or 'http://localhost:8080').rstrip('/')
    elif backend in ('openai', 'custom'):
        p = Provider.from_preset(backend, 'custom')
        p.base_url = (endpoint or '').rstrip('/')
    elif backend == 'anthropic':
        p = Provider.from_preset('anthropic', 'anthropic')
        if endpoint:
            p.base_url = endpoint.rstrip('/')
    else:
        raise ValueError(f"unknown backend: {backend}")
    p.api_key = api_key or ''
    p.qualify = False
    if models:
        p.models = [ModelMap(m, m) for m in models]
        p.autodetect = False
    else:
        # Old behaviour: enumerate for the local backends, refuse for openai.
        p.autodetect = backend in ('ollama', 'llamacpp')
        if not p.autodetect:
            logger.error("--backend %s requires --models "
                         "(the model names you want to share)", backend)
    return p


def _ad_hoc_requested(args) -> bool:
    """True when the run was given single-provider flags (new --provider-url
    or any of the legacy ones), in which case the config file is bypassed."""
    return bool(args.provider_url or args.backend or args.endpoint
                or args.models or args.api_key or args.ollama_host
                or args.ollama_port)


def resolve_providers(args, store: ProviderStore) -> List[Provider]:
    """Decide which providers this run uses.

    Precedence:
      1. legacy/ad-hoc flags (--backend/--endpoint/--models, --provider-url)
         -> a single synthetic provider, config file untouched
      2. the config file, optionally narrowed by --only
      3. nothing configured at all -> local Ollama, exactly like the original
         flag-less `python client.py`
    """
    if _ad_hoc_requested(args):
        backend = args.backend or ('openai' if args.provider_url else 'ollama')
        endpoint = args.provider_url or args.endpoint
        # Old --ollama-host/--ollama-port pair.
        if not endpoint and backend == 'ollama' and (args.ollama_host
                                                     or args.ollama_port):
            host = args.ollama_host or 'localhost'
            port = args.ollama_port or 11434
            endpoint = f"http://{host}:{port}"
        models = [m.strip() for m in args.models.split(',')] if args.models \
            else None
        api_key = args.api_key or os.environ.get('EDITORAI_WORKER_API_KEY')
        needs_key = backend not in ('ollama', 'llamacpp')
        if needs_key and not api_key and sys.stdin.isatty():
            try:
                api_key = getpass.getpass(
                    "API key for this endpoint (hidden, blank = no auth): "
                ).strip() or None
            except (EOFError, KeyboardInterrupt):
                api_key = None
        p = legacy_provider(backend, endpoint, api_key, models)
        if args.header:
            p.headers.update(_parse_headers(args.header))
        if args.autodetect:
            p.autodetect = True
        return [p]

    providers = store.enabled_providers()
    if args.only:
        wanted = [x.strip() for x in args.only.split(',') if x.strip()]
        by_name = {p.name: p for p in store.providers}
        missing = [w for w in wanted if w not in by_name]
        if missing:
            logger.error(f"--only: no such provider(s): {', '.join(missing)}")
            return []
        providers = [by_name[w] for w in wanted]
    if not providers and not store.providers:
        # COMPAT: a bare `python client.py` on a machine with no config must
        # still donate the local Ollama, like every previous version did.
        logger.info("No provider config found - defaulting to local Ollama at "
                    "http://localhost:11434")
        logger.info("Add more providers with: python client.py provider "
                    "wizard")
        providers = [legacy_provider('ollama', None, None, None)]
    return providers


def build_run_parser(argparse_mod):
    ap = argparse_mod.ArgumentParser(
        prog='client.py run',
        description='EditorAI Platinum Worker - donate compute to the network',
        formatter_class=argparse_mod.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # use every provider in the config file (hot-reloaded while running)
  python client.py run

  # only some of them
  python client.py run --only deepseek,mygw

  # ad-hoc, nothing saved: any URL with custom headers
  python client.py run --provider-url https://gw.example.com/v1 \\
      --models fast,smart --header 'X-Org: acme'

  # legacy invocations, unchanged
  python client.py
  python client.py --backend llamacpp --endpoint http://localhost:8080
  python client.py --backend openai --endpoint https://api.example.com \\
      --models glm-4.7-flash,glm-4.5-flash

Manage providers with:  python client.py provider --help
""")
    ap.add_argument('--coordinator',
                    default=os.environ.get('PLATINUM_COORDINATOR',
                                           DEFAULT_COORDINATOR),
                    help=f'Coordinator server URL (default: {DEFAULT_COORDINATOR})')
    ap.add_argument('--config', default=None,
                    help=f'Provider config file (default: {default_config_path()})')
    ap.add_argument('--only',
                    help='Comma-separated provider names to use this run')
    ap.add_argument('--worker-id', help='Custom worker ID')
    ap.add_argument('--concurrency', type=int, default=1,
                    help='Jobs to run at once (default 1)')
    ap.add_argument('--poll-interval', type=float, default=2.0,
                    help='Seconds between empty work polls (default 2)')
    ap.add_argument('--reload-interval', type=float, default=5.0,
                    help='Seconds between provider-config checks; 0 disables '
                         'hot reload (default 5)')
    ap.add_argument('--no-reload', action='store_true',
                    help='Disable provider-config hot reload')

    adhoc = ap.add_argument_group(
        'ad-hoc / legacy single-provider flags',
        'Use a provider without saving it to the config file.')
    adhoc.add_argument('--provider-url',
                       help='Any endpoint URL to serve from this run')
    adhoc.add_argument('--backend',
                       choices=['ollama', 'llamacpp', 'openai', 'anthropic',
                                'custom'],
                       help='API flavour of the ad-hoc endpoint '
                            '(default: ollama, or openai with --provider-url)')
    adhoc.add_argument('--endpoint', help='(alias of --provider-url)')
    adhoc.add_argument('--api-key',
                       help='API key for the ad-hoc endpoint. If omitted you '
                            'are prompted (or set EDITORAI_WORKER_API_KEY).')
    adhoc.add_argument('--models',
                       help='Comma-separated tags to advertise. Required for '
                            'openai/custom; overrides auto-enumeration for '
                            'ollama/llamacpp.')
    adhoc.add_argument('--header', action='append', metavar='NAME: VALUE',
                       help='Extra header for the ad-hoc endpoint (repeatable)')
    adhoc.add_argument('--autodetect', action='store_true',
                       help='Autodetect the ad-hoc endpoint\'s models')
    # Back-compat aliases from the old Ollama-only client.
    adhoc.add_argument('--ollama-host', help='(compat) Ollama host')
    adhoc.add_argument('--ollama-port', type=int, help='(compat) Ollama port')
    adhoc.add_argument('--worker-port', type=int, help='(compat, ignored)')
    return ap


async def run_worker(argv: List[str]) -> int:
    import argparse
    ap = build_run_parser(argparse)
    args = ap.parse_args(argv)

    try:
        store = ProviderStore(args.config)
    except RuntimeError as e:
        logger.error(str(e))
        return 2

    providers = resolve_providers(args, store)
    if not providers:
        if store.providers:
            logger.error("No usable providers for this run "
                         "(all disabled? see `provider list`).")
        else:
            logger.error("No providers configured yet.")
            logger.error("Try:  python client.py provider wizard")
        return 2

    ad_hoc = _ad_hoc_requested(args)
    reload_interval = 0.0 if (args.no_reload or ad_hoc) else args.reload_interval

    worker = PlatinumWorker(
        coordinator_url=args.coordinator,
        providers=providers,
        worker_id=args.worker_id,
        config_path=None if ad_hoc else store.path,
        reload_interval=reload_interval,
        poll_interval=args.poll_interval,
        concurrency=args.concurrency,
    )
    await worker.start()
    return 0

# ── entry point ──────────────────────────────────────────────────────────────
# Management subcommands route into the in-file CLI; anything else is a worker
# run (so the historical flag-only invocation still works).
CLI_COMMANDS = {'provider', 'providers', 'tags', 'presets', 'wizard',
                'config-path', 'add', 'bulk', 'import', 'add-many'}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in CLI_COMMANDS:
        if argv[0] == 'providers':
            argv[0] = 'provider'
        return run_cli(argv)
    if argv and argv[0] == 'run':
        argv = argv[1:]
    try:
        return asyncio.run(run_worker(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
