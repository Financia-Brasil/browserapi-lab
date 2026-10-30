# browserapi-server

OpenAI-compatible API server for AI chat automation via browserapi-lab.

## Features

- **OpenAI-compatible API**: `/v1/chat/completions` with streaming support
- **Multiple AI chat sites**: Fixture (testing), LMArena, Gemini, OpenChat
- **Session management**: Persistent browser profiles with lock files
- **Element discovery**: Inspect pages for automation selectors
- **Response extraction**: Clean markdown-like extraction from AI responses
- **Real streaming**: MutationObserver-based streaming observation
- **Production-ready**: Docker, systemd, Nginx configs included

## Quick Start

### Development

```bash
# Install dependencies
pip install -e ./browserapi_server

# Run server
python -m uvicorn browserapi_server.main:app --host 0.0.0.0 --port 8000
```

### Production (Docker)

```bash
# Build and run
docker compose -f docker-compose.yml up -d

# Or use deployment script
./deploy.sh production
```

### systemd Service

```bash
sudo cp browserapi-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now browserapi-server
```

## API Endpoints

### Health & Models

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/v1/models` | List available models |
| GET | `/doctor` | Environment diagnostics |

### Chat Completions (OpenAI Compatible)

```bash
# Non-streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "browserapi-default",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'

# Streaming (SSE)
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "browserapi-default",
    "messages": [{"role": "user", "content": "Tell me a joke"}],
    "stream": true
  }'
```

**Request Parameters:**
- `model`: Model ID (e.g., `browserapi-default`)
- `messages`: Array of `{role, content}` objects
- `stream`: Enable SSE streaming
- `site`: Target site (`fixture`, `lmarena`, `gemini`, `openchat`)
- `user`: Profile/session identifier
- `stop`: Stop sequences

### Session Management

```bash
# List profiles
curl -X POST http://localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"profile": "api_sessions", "action": "list"}'

# Profile info
curl -X POST http://localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"profile": "api_sessions", "action": "info"}'

# Check session validity
curl -X POST http://localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"profile": "api_sessions", "action": "check", "url": "https://chat.lmsys.org"}'

# Export storage state
curl -X POST http://localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"profile": "api_sessions", "action": "export", "url": "https://chat.lmsys.org", "export_path": "/tmp/state.json"}'
```

### Inspection & Extraction

```bash
# Inspect page elements
curl -X POST http://localhost:8000/v1/inspect \
  -H "Content-Type: application/json" \
  -d '{"url": "https://chat.lmsys.org", "profile": "lmarena"}'

# Extract response
curl -X POST http://localhost:8000/v1/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://chat.lmsys.org", "profile": "lmarena", "format": "markdown_like"}'
```

## Supported Sites

| Site | URL | Status |
|------|-----|--------|
| Fixture (testing) | `file://.../fake_chat.html` | ✅ Ready |
| LMArena | `https://chat.lmsys.org` | ⚠️ Selectors need verification |
| Gemini | `https://gemini.google.com` | ⚠️ Selectors need verification |
| OpenChat | `https://chat.openchat.ai` | ⚠️ Selectors need verification |

**Note**: Real sites require manual login. Run in headed mode (`headless: false`) and wait for login prompt.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYTHONUNBUFFERED` | `1` | Python output buffering |
| `PLAYWRIGHT_BROWSERS_PATH` | `/ms-playwright` | Playwright browser cache |

### ServerConfig

```python
ServerConfig(
    default_profile="api_sessions",
    headless=True,
    browser_path=None,  # Auto-detect
    default_model="browserapi-default",
    max_concurrent_sessions=10,
    default_site="fixture"
)
```

## Architecture

```
browserapi-server/
├── main.py              # FastAPI application
├── Dockerfile           # Multi-stage Docker build
├── docker-compose.yml   # Production deployment
├── nginx.conf           # Reverse proxy config
├── browserapi-server.service  # systemd unit
└── deploy.sh            # Deployment script
```

## Dependencies

- **Python**: 3.11+
- **Playwright**: 1.40+ (with Chromium)
- **FastAPI**: 0.104+
- **uvicorn**: 0.24+
- **pydantic**: 2.5+
- **sse-starlette**: 1.6+

## Testing

```bash
# Run tests
pytest tests/

# Test chat completion
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "browserapi-default", "messages": [{"role": "user", "content": "test"}]}'

# Test streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "browserapi-default", "messages": [{"role": "user", "content": "test"}], "stream": true}'
```

## License

MIT