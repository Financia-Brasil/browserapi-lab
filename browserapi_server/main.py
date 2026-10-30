"""
OpenAI-Compatible API Server for browserapi-lab
Phase 2: Build API layer on top of proven browserapi-lab modules
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# Import browserapi-lab modules
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from browserapi_lab.browser import BrowserManager, get_browser_path
from browserapi_lab.discover import discover_all
from browserapi_lab.send import MessageSender, summarize_results
from browserapi_lab.observe import StreamObserver
from browserapi_lab.extract import ResponseExtractor
from browserapi_lab.session import SessionManager
from browserapi_lab.environment import run_doctor


# ===== OpenAI-Compatible Models =====


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = "browserapi-default"
    messages: List[ChatMessage]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    stop: Optional[List[str]] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    user: Optional[str] = None
    site: Optional[str] = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Dict[str, int]


class ChatCompletionChunkChoice(BaseModel):
    index: int
    delta: Dict[str, Any]
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatCompletionChunkChoice]


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "browserapi-lab"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelInfo]


# ===== Site Configuration =====


@dataclass
class SiteConfig:
    """Configuration for a specific chat site."""

    name: str
    url: str
    input_selector: str
    send_button_selector: str
    container_selector: str
    assistant_selector: str
    stop_button_selector: Optional[str] = None
    copy_button_selector: Optional[str] = None
    busy_indicator_selector: Optional[str] = None
    requires_login: bool = True
    test_mode_js: Optional[str] = None  # JS to enable test mode (instant responses)


# Built-in site configurations
BUILTIN_SITES = {
    "fixture": SiteConfig(
        name="fixture",
        url="file:///home/tork/browserapi-lab/fixtures/fake_chat.html",
        input_selector="#composer",
        send_button_selector="#send",
        container_selector="#conversation",
        assistant_selector='[data-role="assistant"]',
        stop_button_selector="#stop",
        copy_button_selector=None,
        busy_indicator_selector=None,
        requires_login=False,
        test_mode_js=None,
    ),
    "lmarena": SiteConfig(
        name="lmarena",
        url="https://chat.lmsys.org",
        input_selector='textarea[data-testid="chat-input"]',
        send_button_selector='button[data-testid="send-button"]',
        container_selector='[data-testid="conversation"]',
        assistant_selector='[data-testid*="model-response"]',
        stop_button_selector='button[data-testid="stop-button"]',
        copy_button_selector='button[data-testid="copy-button"]',
        busy_indicator_selector='[data-testid="generating-indicator"]',
        requires_login=True,
    ),
    "gemini": SiteConfig(
        name="gemini",
        url="https://gemini.google.com",
        input_selector='rich-textarea[placeholder*="Enter a prompt"]',
        send_button_selector='button[aria-label*="Send"]',
        container_selector='[data-testid="conversation"]',
        assistant_selector='[data-testid*="model-response"]',
        requires_login=True,
    ),
    "openchat": SiteConfig(
        name="openchat",
        url="https://chat.openchat.ai",
        input_selector='textarea[placeholder*="Message"]',
        send_button_selector='button[type="submit"]',
        container_selector='[data-testid="messages"]',
        assistant_selector='[data-testid*="assistant"]',
        requires_login=True,
    ),
}


# ===== Server Configuration =====


@dataclass
class ServerConfig:
    default_profile: str = "api_sessions"
    headless: bool = True
    browser_path: Optional[str] = None
    default_model: str = "browserapi-default"
    max_concurrent_sessions: int = 10
    default_site: str = "fixture"


@dataclass
class ActiveSession:
    profile_name: str
    manager: BrowserManager
    page: Any
    created_at: float
    last_used: float
    message_count: int = 0
    site_name: str = "fixture"
    site_url: str = ""
    initialized: bool = False


class APIServer:
    """Manages browser sessions and processes chat completions."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.sessions: Dict[str, ActiveSession] = {}
        self.session_manager = SessionManager()
        self._lock = asyncio.Lock()

    def get_site_config(self, site_name: str) -> SiteConfig:
        """Get site configuration by name."""
        if site_name in BUILTIN_SITES:
            return BUILTIN_SITES[site_name]
        # Default to fixture
        return BUILTIN_SITES["fixture"]

    async def get_or_create_session(
        self, profile_name: Optional[str] = None, site_name: Optional[str] = None
    ) -> ActiveSession:
        """Get existing session or create new one."""
        async with self._lock:
            profile = profile_name or self.config.default_profile
            site = site_name or self.config.default_site
            site_config = self.get_site_config(site)

            if profile in self.sessions:
                session = self.sessions[profile]
                session.last_used = time.time()
                # If site changed, we'll need to reinitialize
                if session.site_name != site:
                    await self._reinitialize_session(session, site_config)
                return session

            # Check limit
            if len(self.sessions) >= self.config.max_concurrent_sessions:
                # Remove oldest session
                oldest = min(self.sessions.values(), key=lambda s: s.last_used)
                await self.close_session(oldest.profile_name)

            # Create new session
            manager = BrowserManager(profile, self.config.headless)
            browser_path = self.config.browser_path or await get_browser_path()
            page = await manager.start(browser_path)

            session = ActiveSession(
                profile_name=profile,
                manager=manager,
                page=page,
                created_at=time.time(),
                last_used=time.time(),
                site_name=site,
                site_url=site_config.url,
            )
            self.sessions[profile] = session
            await self._initialize_session(session, site_config)
            return session

    async def _initialize_session(
        self, session: ActiveSession, site_config: SiteConfig
    ) -> None:
        """Initialize session page with site configuration."""
        if session.initialized and session.site_name == site_config.name:
            return

        try:
            # Navigate to site
            await session.page.goto(site_config.url, wait_until="domcontentloaded")
            await session.page.wait_for_load_state("networkidle")
            session.site_url = site_config.url

            # Enable test mode if available (ignora se a função não existir na página)
            if site_config.test_mode_js:
                try:
                    await session.page.evaluate(site_config.test_mode_js)
                except Exception:
                    pass

            session.site_name = site_config.name
            session.initialized = True
        except Exception as e:
            raise HTTPException(
                500, f"Failed to initialize session for {site_config.name}: {str(e)}"
            )

    async def _reinitialize_session(
        self, session: ActiveSession, site_config: SiteConfig
    ) -> None:
        """Reinitialize session for a different site."""
        session.initialized = False
        await self._initialize_session(session, site_config)

    async def close_session(self, profile_name: str) -> bool:
        """Close and remove a session."""
        async with self._lock:
            if profile_name in self.sessions:
                session = self.sessions[profile_name]
                try:
                    await session.manager.close()
                except Exception:
                    pass  # Ignore errors if already closed
                del self.sessions[profile_name]
                return True
            return False

    async def cleanup_idle_sessions(self, max_age: float = 3600) -> int:
        """Remove sessions older than max_age seconds."""
        async with self._lock:
            now = time.time()
            to_remove = [
                name
                for name, sess in self.sessions.items()
                if now - sess.last_used > max_age
            ]
            for name in to_remove:
                await self.close_session(name)
            return len(to_remove)


# ===== Global Server Instance =====

server_config = ServerConfig()
api_server = APIServer(server_config)


# ===== Lifespan =====


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    print("🚀 browserapi-server starting...")
    print(f"   Default profile: {server_config.default_profile}")
    print(f"   Headless: {server_config.headless}")
    yield
    # Shutdown
    print("🛑 browserapi-server shutting down...")
    for profile_name in list(api_server.sessions.keys()):
        await api_server.close_session(profile_name)


# ===== FastAPI App =====

app = FastAPI(
    title="browserapi-server",
    description="OpenAI-compatible API for AI chat automation via browserapi-lab",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Health & Info Endpoints =====


@app.get("/")
async def root():
    return {
        "service": "browserapi-server",
        "version": "0.2.0",
        "description": "OpenAI-compatible API for AI chat automation via browserapi-lab",
        "endpoints": {
            "health": "/health",
            "models": "/v1/models",
            "chat_completions": "/v1/chat/completions",
            "sessions": "/v1/sessions",
            "inspect": "/v1/inspect",
            "extract": "/v1/extract",
            "doctor": "/doctor",
        },
        "documentation": "https://github.com/browserapi-lab",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "browserapi-server", "version": "0.2.0"}


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """List available models (OpenAI-compatible)."""
    return ModelsResponse(
        data=[
            ModelInfo(
                id="browserapi-default",
                created=int(time.time()),
                owned_by="browserapi-lab",
            ),
            ModelInfo(
                id="browserapi-fixtured",
                created=int(time.time()),
                owned_by="browserapi-lab",
            ),
        ]
    )


@app.get("/doctor")
async def doctor_endpoint():
    """Run environment doctor."""
    report = run_doctor()
    return report


@app.get("/v1")
async def v1_root():
    return {
        "issuer": "browserapi-lab",
        "authorization_endpoint": "http://127.0.0.1:8000/v1/auth/authorize",
        "token_endpoint": "http://127.0.0.1:8000/v1/auth/token",
        "jwks_uri": "http://127.0.0.1:8000/v1/.well-known/jwks.json",
        "scopes_supported": ["chat", "chat.completions"],
        "response_types_supported": ["text", "stream"],
        "grant_types_supported": ["api_key"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "claims_supported": ["sub", "name", "email"],
    }


@app.get("/.well-known/openai-configuration")
async def openai_configuration():
    """OpenAI-compatible configuration endpoint for provider discovery."""
    return {
        "issuer": "browserapi-lab",
        "authorization_endpoint": "http://127.0.0.1:8000/v1/auth/authorize",
        "token_endpoint": "http://127.0.0.1:8000/v1/auth/token",
        "jwks_uri": "http://127.0.0.1:8000/v1/.well-known/jwks.json",
        "scopes_supported": ["chat", "chat.completions"],
        "response_types_supported": ["text", "stream"],
        "grant_types_supported": ["api_key"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "claims_supported": ["sub", "name", "email"],
    }


# ===== Chat Completions =====


async def wait_for_stable_text(
    page,
    assistant_selector: str,
    container_selector: str,
    max_wait_s: float = 120.0,
    stable_s_for: float = 2.0,
    poll_s: float = 0.2,
) -> str:
    """Aguarda o texto do assistente estabilizar (parar de mudar) antes de extrair.

    Isso evita respostas cortadas: só retorna depois que o texto permanece inalterado
    por stable_s_for segundos consecutivos, ou após max_wait_s segundos totais.
    """
    import time

    start = time.time()
    last_text = ""
    stable_since = None

    while (time.time() - start) < max_wait_s:
        text = await page.evaluate(
            """([assistantSel, containerSel]) => {
                const container = document.querySelector(containerSel);
                if (!container) return '';
                const assistants = container.querySelectorAll(assistantSel);
                if (assistants.length === 0) return '';
                return assistants[assistants.length - 1].textContent || '';
            }""",
            [assistant_selector, container_selector],
        )

        if text == last_text:
            if stable_since is None:
                stable_since = time.time()
            elif (time.time() - stable_since) >= stable_s_for:
                return text
        else:
            stable_since = None
            last_text = text

        await asyncio.sleep(poll_s)

    # Timeout: retorna o último texto capturado (mesmo que não esteja totalmente estável)
    return last_text


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest, http_request: Request):
    """OpenAI-compatible chat completions endpoint."""
    # Get or create session
    profile = request.user or server_config.default_profile
    site = getattr(request, "site", None) or server_config.default_site
    session = await api_server.get_or_create_session(profile, site)
    page = session.page
    site_config = api_server.get_site_config(session.site_name)
    session.message_count += 1
    session.last_used = time.time()

    # Extract user message (last user message)
    user_messages = [m for m in request.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(400, "No user message found")
    user_message = user_messages[-1].content

    # System message (first if present)
    system_messages = [m for m in request.messages if m.role == "system"]
    system_prompt = system_messages[0].content if system_messages else ""

    # Combine system + user message
    full_message = (
        f"{system_prompt}\n\n{user_message}".strip() if system_prompt else user_message
    )

    try:
        # Send message using site-specific selectors
        sender = MessageSender(page)
        input_sel = site_config.input_selector
        btn_sel = site_config.send_button_selector

        # Use best method for textarea: fill
        result = await sender.send_textarea_fill(full_message, input_sel, btn_sel)

        if not result.success:
            raise HTTPException(500, f"Failed to send message: {result.error}")

        # Wait for streaming to complete: first wait for input re-enabled,
        # then wait for the assistant text to stabilize (stop changing).
        for _ in range(300):
            disabled = await page.locator(input_sel).evaluate("el => el.disabled")
            if not disabled:
                break
            await asyncio.sleep(0.1)
        else:
            raise HTTPException(504, "Streaming timeout")

        # Aguarda estabilidade do texto antes de extrair (evita resposta cortada)
        assistant_sel = site_config.assistant_selector
        container_sel = site_config.container_selector
        stable_text = await wait_for_stable_text(
            page,
            assistant_selector=assistant_sel,
            container_selector=container_sel,
            max_wait_s=120.0,
            stable_s_for=2.0,
            poll_s=0.2,
        )

        # Extract response from stabilized text
        extractor = ResponseExtractor(page)
        extract_result = await extractor.extract_last_assistant(
            assistant_sel, "markdown_like", container_sel
        )

        # Usa o texto estável se a extração retornar vazio ou menor
        response_text = extract_result.text or stable_text
        if stable_text and len(stable_text) > len(response_text):
            response_text = stable_text

        # Handle stop sequences
        if request.stop:
            for stop_seq in request.stop:
                if stop_seq in response_text:
                    response_text = response_text.split(stop_seq)[0]
                    break

        # Build response
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        if request.stream:
            return EventSourceResponse(
                stream_response(
                    completion_id,
                    created,
                    request.model,
                    response_text,
                    session,
                    site_config,
                ),
                media_type="text/event-stream",
            )

        return ChatCompletionResponse(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=response_text),
                    finish_reason="stop",
                )
            ],
            usage={
                "prompt_tokens": len(full_message) // 4,  # rough estimate
                "completion_tokens": len(response_text) // 4,
                "total_tokens": (len(full_message) + len(response_text)) // 4,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Internal error: {str(e)}")


async def stream_response(
    completion_id: str,
    created: int,
    model: str,
    text: str,
    session: Optional["ActiveSession"] = None,
    site_config: Optional[SiteConfig] = None,
) -> AsyncGenerator[str, None]:
    """Stream response in OpenAI format using actual browser streaming."""
    # Send initial chunk with role
    chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0, delta={"role": "assistant"}, finish_reason=None
            )
        ],
    )
    yield chunk.model_dump_json()

    # If we have a session and site config, do actual streaming observation
    if session and site_config and session.page:
        # Set up stream observer
        observer = StreamObserver(
            session.page,
            site_config.container_selector,
            site_config.assistant_selector,
            site_config.stop_button_selector,
            site_config.copy_button_selector,
            site_config.busy_indicator_selector,
        )

        await observer._inject_observer()

        # Stream tokens as they arrive
        last_text = ""
        async for chunk_text in _watch_streaming(session.page, site_config, observer):
            if chunk_text and chunk_text != last_text:
                new_text = (
                    chunk_text[len(last_text) :]
                    if chunk_text.startswith(last_text)
                    else chunk_text
                )
                if new_text:
                    chunk = ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0, delta={"content": new_text}, finish_reason=None
                            )
                        ],
                    )
                    yield chunk.model_dump_json()
                last_text = chunk_text

        # Final chunk
        chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[
                ChatCompletionChunkChoice(index=0, delta={}, finish_reason="stop")
            ],
        )
        yield chunk.model_dump_json()
        yield "[DONE]"
    else:
        # Fallback: simulate streaming by splitting words
        words = text.split()
        for i, word in enumerate(words):
            chunk_text = word + (" " if i < len(words) - 1 else "")
            chunk = ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0, delta={"content": chunk_text}, finish_reason=None
                    )
                ],
            )
            yield chunk.model_dump_json()
            await asyncio.sleep(0.01)

        # Final chunk
        chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[
                ChatCompletionChunkChoice(index=0, delta={}, finish_reason="stop")
            ],
        )
        yield chunk.model_dump_json()
        yield "[DONE]"


async def _watch_streaming(
    page: Any, site_config: SiteConfig, observer: StreamObserver
) -> AsyncGenerator[str, None]:
    """Watch for streaming content and yield accumulated text."""
    last_yielded = ""
    mutation_count = 0

    # Wait for initial content
    await asyncio.sleep(0.5)

    while True:
        try:
            # Get current assistant message text
            text = await page.evaluate(f"""() => {{
                const container = document.querySelector('{site_config.container_selector}');
                if (!container) return '';
                const assistants = container.querySelectorAll('{site_config.assistant_selector}');
                if (assistants.length === 0) return '';
                return assistants[assistants.length - 1].textContent || '';
            }}""")

            if text and text != last_yielded:
                last_yielded = text
                yield text

            # Check if streaming is done via UI signals
            if site_config.stop_button_selector:
                stop_visible = await page.evaluate(f"""() => {{
                    const el = document.querySelector('{site_config.stop_button_selector}');
                    return el ? window.getComputedStyle(el).display !== 'none' : false;
                }}""")
                if not stop_visible:
                    # Check copy button
                    copy_visible = await page.evaluate(f"""() => {{
                        const el = document.querySelector('{site_config.copy_button_selector}');
                        return el ? window.getComputedStyle(el).display !== 'none' : false;
                    }}""")
                    if copy_visible:
                        break

            # Also check busy indicator
            if site_config.busy_indicator_selector:
                busy = await page.evaluate(f"""() => {{
                    const el = document.querySelector('{site_config.busy_indicator_selector}');
                    return el ? el.getAttribute('aria-busy') === 'true' : false;
                }}""")
                if not busy:
                    # Give it a moment to settle
                    await asyncio.sleep(0.5)
                    final_text = await page.evaluate(f"""() => {{
                        const container = document.querySelector('{site_config.container_selector}');
                        if (!container) return '';
                        const assistants = container.querySelectorAll('{site_config.assistant_selector}');
                        if (assistants.length === 0) return '';
                        return assistants[assistants.length - 1].textContent || '';
                    }}""")
                    if final_text != last_yielded:
                        last_yielded = final_text
                        yield final_text
                    break

            await asyncio.sleep(0.1)

        except Exception as e:
            print(f"Stream watch error: {e}")
            break


# ===== Session Management =====


class SessionRequest(BaseModel):
    profile: str = "api_sessions"
    action: str = Field(..., pattern="^(list|info|export|import|clear|delete|check)$")
    url: Optional[str] = None
    import_path: Optional[str] = None
    export_path: Optional[str] = None


@app.post("/v1/sessions")
async def manage_session(request: SessionRequest):
    """Manage browser sessions."""
    try:
        if request.action == "list":
            profiles = api_server.session_manager.list_profiles()
            return {"profiles": [asdict(p) for p in profiles]}

        elif request.action == "info":
            info = api_server.session_manager.get_profile_info(request.profile)
            return {"profile": asdict(info) if info else None}

        elif request.action == "export":
            if not request.url:
                raise HTTPException(400, "url required for export")
            session = await api_server.get_or_create_session(request.profile)
            output = await api_server.session_manager.export_storage_state(
                session.manager.context,
                request.profile,
                Path(request.export_path) if request.export_path else None,
            )
            return {"exported": str(output)}

        elif request.action == "import":
            if not request.import_path:
                raise HTTPException(400, "import_path required")
            session = await api_server.get_or_create_session(request.profile)
            if request.url:
                await session.page.goto(request.url, wait_until="domcontentloaded")
                await session.page.wait_for_load_state("networkidle")
            success = await api_server.session_manager.import_storage_state(
                session.manager.context, request.profile, Path(request.import_path)
            )
            return {"success": success}

        elif request.action == "clear":
            success = await api_server.session_manager.clear_profile(request.profile)
            return {"success": success}

        elif request.action == "delete":
            success = api_server.session_manager.delete_profile(request.profile)
            if request.profile in api_server.sessions:
                await api_server.close_session(request.profile)
            return {"success": success}

        elif request.action == "check":
            if not request.url:
                raise HTTPException(400, "url required for check")
            session = await api_server.get_or_create_session(request.profile)
            await session.page.goto(request.url, wait_until="domcontentloaded")
            await session.page.wait_for_load_state("networkidle")
            result = await api_server.session_manager.check_session_validity(
                session.page, expected_url_contains=request.url
            )
            return result

        else:
            raise HTTPException(400, f"Unknown action: {request.action}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Session error: {str(e)}")


@app.delete("/v1/sessions/{profile}")
async def delete_session(profile: str):
    """Close and delete a session."""
    success = await api_server.close_session(profile)
    if success:
        api_server.session_manager.delete_profile(profile)
    return {"success": success, "profile": profile}


# ===== Request Models =====


class InspectRequest(BaseModel):
    url: str
    profile: str = "api_sessions"
    headless: bool = True


class ExtractRequest(BaseModel):
    url: str
    profile: str = "api_sessions"
    format: str = "markdown_like"
    assistant_selector: Optional[str] = None
    container_selector: Optional[str] = None
    compare: bool = False


# ===== Debug/Inspection Endpoints =====


@app.post("/v1/inspect")
async def inspect_page(request: InspectRequest):
    """Discover element candidates on a page."""
    session = await api_server.get_or_create_session(request.profile)
    await session.page.goto(request.url, wait_until="domcontentloaded")
    await session.page.wait_for_load_state("networkidle")

    result = await discover_all(session.page)
    return {"url": request.url, "candidates": result}


@app.post("/v1/extract")
async def extract_response(request: ExtractRequest):
    """Extract last assistant response."""
    session = await api_server.get_or_create_session(request.profile)
    await session.page.goto(request.url, wait_until="domcontentloaded")
    await session.page.wait_for_load_state("networkidle")

    extractor = ResponseExtractor(session.page)
    ass_sel = request.assistant_selector or '[data-testid*="assistant"]'
    cont_sel = request.container_selector or '[role="log"]'

    if request.compare:
        results = await extractor.extract_all_methods(ass_sel, cont_sel)
        return {k: asdict(v) for k, v in results.items()}
    else:
        result = await extractor.extract_last_assistant(
            ass_sel, request.format, cont_sel
        )
        return asdict(result)


# ===== Main =====

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
