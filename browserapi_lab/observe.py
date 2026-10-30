"""Streaming observation module for browserapi-lab."""
import asyncio
import time
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Callable
from playwright.async_api import Page


@dataclass
class StreamMetrics:
    """Metrics for a streaming response."""
    ttft_ms: Optional[float] = None           # Time to first token
    total_duration_ms: float = 0              # Total streaming duration
    mutation_count: int = 0                   # Number of DOM mutations
    stall_count: int = 0                      # Number of stalls (>stall_threshold)
    stall_durations: List[float] = field(default_factory=list)  # Duration of each stall
    final_text_length: int = 0                # Final response length
    ended_by: str = "unknown"                 # "stability", "ui_signal", "timeout", "error"
    started_at: float = 0                     # Unix timestamp start
    ended_at: float = 0                       # Unix timestamp end
    error: Optional[str] = None               # Error if any


@dataclass
class StreamEvent:
    """Single streaming event."""
    timestamp: float
    event_type: str  # "mutation", "first_token", "stall_start", "stall_end", "ui_signal", "end"
    details: Dict[str, Any]


class StreamObserver:
    """Observes streaming responses using MutationObserver + UI signals."""

    def __init__(
        self,
        page: Page,
        container_selector: str,
        assistant_selector: str,
        stop_selector: Optional[str] = None,
        copy_selector: Optional[str] = None,
        busy_selector: Optional[str] = None,
    ):
        self.page = page
        self.container_selector = container_selector
        self.assistant_selector = assistant_selector
        self.stop_selector = stop_selector
        self.copy_selector = copy_selector
        self.busy_selector = busy_selector

        self.metrics = StreamMetrics()
        self.events: List[StreamEvent] = []
        self._observing = False
        self._last_text = ""
        self._stall_start: Optional[float] = None
        self._stall_threshold = 2.0  # seconds
        self._stability_window = 1.5  # seconds of no mutations
        self._last_mutation_time = 0
        self._first_token_received = False

    async def start(
        self,
        strategy: str = "hybrid",
        timeout: float = 120.0,
        stall_threshold: float = 2.0,
        stability_window: float = 1.5,
    ) -> StreamMetrics:
        """Start observing streaming response."""
        self._stall_threshold = stall_threshold
        self._stability_window = stability_window
        self.metrics.started_at = time.time()
        self._last_mutation_time = time.time()
        self._first_token_received = False
        self._stall_start = None
        self._last_text = ""
        self.events = []
        self.metrics = StreamMetrics(started_at=self.metrics.started_at)

        # Inject MutationObserver into page
        await self._inject_observer()

        # Start observation loop
        self._observing = True
        try:
            await self._observation_loop(strategy, timeout)
        finally:
            self._observing = False
            await self._cleanup_observer()

        self.metrics.ended_at = time.time()
        self.metrics.total_duration_ms = (self.metrics.ended_at - self.metrics.started_at) * 1000

        # Capture final text length
        try:
            final_text = await self.page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    return el ? el.textContent || '' : '';
                }""",
                self.assistant_selector
            )
            self.metrics.final_text_length = len(final_text)
        except Exception:
            pass

        return self.metrics

    async def _inject_observer(self) -> None:
        """Inject MutationObserver into the page."""
        script = """
        (() => {
            window.__streamObserver = {
                callbacks: [],
                observer: null,
                container: null,
                lastText: '',
                mutationCount: 0,
                
                init(containerSelector, assistantSelector) {
                    this.container = document.querySelector(containerSelector);
                    if (!this.container) return false;
                    
                    this.observer = new MutationObserver((mutations) => {
                        // Find the LAST assistant message (the one being streamed)
                        const assistantEls = this.container.querySelectorAll(assistantSelector);
                        const assistantEl = assistantEls[assistantEls.length - 1];
                        if (!assistantEl) return;
                        
                        this.mutationCount += mutations.length;
                        
                        const text = assistantEl.textContent || '';
                        const timestamp = performance.now();
                        
                        this.callbacks.forEach(cb => cb({
                            type: 'mutation',
                            timestamp: timestamp,
                            textLength: text.length,
                            textPreview: text.slice(0, 100),
                            mutationCount: mutations.length
                        }));
                    });
                    
                    this.observer.observe(this.container, {
                        childList: true,
                        subtree: true,
                        characterData: true,
                        attributes: true,
                        attributeFilter: ['class', 'aria-busy', 'data-testid']
                    });
                    return true;
                },
                
                onEvent(callback) {
                    this.callbacks.push(callback);
                },
                
                disconnect() {
                    if (this.observer) {
                        this.observer.disconnect();
                        this.observer = null;
                    }
                    this.callbacks = [];
                },
                
                checkUISignals(stopSelector, copySelector, busySelector) {
                    const signals = {};
                    if (stopSelector) {
                        const stopEl = document.querySelector(stopSelector);
                        signals.stopVisible = stopEl ? window.getComputedStyle(stopEl).display !== 'none' : false;
                        signals.stopHidden = stopEl ? stopEl.hidden : true;
                    }
                    if (copySelector) {
                        const copyEl = document.querySelector(copySelector);
                        signals.copyVisible = copyEl ? window.getComputedStyle(copyEl).display !== 'none' : false;
                    }
                    if (busySelector) {
                        const busyEl = document.querySelector(busySelector);
                        signals.busy = busyEl ? busyEl.getAttribute('aria-busy') === 'true' : false;
                    }
                    return signals;
                }
            };
        })();
        """
        await self.page.evaluate(script)

        # Initialize with selectors
        await self.page.evaluate(
            """([container, assistant]) => window.__streamObserver.init(container, assistant)""",
            [self.container_selector, self.assistant_selector]
        )

        # Set up callback bridge
        try:
            await self.page.expose_function("__streamCallback", self._on_mutation_event)
        except Exception:
            # Function already exposed, ignore
            pass

        await self.page.evaluate("""
            () => {
                window.__streamObserver.onEvent((event) => {
                    window.__streamCallback(event);
                });
            }
        """)

    def _on_mutation_event(self, event: Dict[str, Any]) -> None:
        """Handle mutation events from page."""
        now = time.time()
        
        if event["type"] == "mutation":
            text_len = event.get("textLength", 0)
            
            # First token
            if not self._first_token_received and text_len > 0:
                self._first_token_received = True
                self.metrics.ttft_ms = (now - self.metrics.started_at) * 1000
                self.events.append(StreamEvent(
                    timestamp=now,
                    event_type="first_token",
                    details={"text_length": text_len}
                ))
            
            # Track mutations
            self.metrics.mutation_count += event.get("mutationCount", 1)
            self._last_mutation_time = now
            
            # Check for stall recovery
            if self._stall_start is not None:
                stall_duration = now - self._stall_start
                self.metrics.stall_durations.append(stall_duration)
                self.events.append(StreamEvent(
                    timestamp=now,
                    event_type="stall_end",
                    details={"stall_duration_ms": stall_duration * 1000}
                ))
                self._stall_start = None
            
            self._last_text = event.get("textPreview", "")

    async def _observation_loop(self, strategy: str, timeout: float) -> None:
        """Main observation loop."""
        start = time.time()
        stable_since = 0
        streaming_active = False
        
        while self._observing and (time.time() - start) < timeout:
            await asyncio.sleep(0.1)
            now = time.time()
            elapsed = now - self.metrics.started_at
            
            # Check UI signals
            ui_signals = await self._check_ui_signals()
            
            # Track streaming state from UI signals
            was_streaming = streaming_active
            streaming_active = ui_signals.get("busy") is True or ui_signals.get("stopVisible") is True
            
            # If streaming just ended (was active, now not), stop immediately
            if was_streaming and not streaming_active:
                self.metrics.ended_by = "ui_signal"
                self.events.append(StreamEvent(
                    timestamp=now,
                    event_type="ui_signal",
                    details=ui_signals
                ))
                return
            
            # Strategy: ui_signals - stop when UI indicates done
            if strategy in ("ui_signals", "hybrid"):
                if self._should_stop_by_ui(ui_signals):
                    self.metrics.ended_by = "ui_signal"
                    self.events.append(StreamEvent(
                        timestamp=now,
                        event_type="ui_signal",
                        details=ui_signals
                    ))
                    return
            
            # Check if we have reliable UI signals (busy, stop, copy indicators)
            has_ui_signals = (
                self.stop_selector is not None or 
                self.copy_selector is not None or 
                self.busy_selector is not None
            )
            
            # Strategy: stability - stop when no mutations for stability_window
            # Only use as fallback in hybrid mode when UI signals are not reliable
            use_stability = strategy == "stability" or (strategy == "hybrid" and not has_ui_signals)
            if use_stability:
                if self._first_token_received:
                    time_since_mutation = now - self._last_mutation_time
                    if time_since_mutation >= self._stability_window:
                        if stable_since == 0:
                            stable_since = now
                        elif now - stable_since >= self._stability_window:
                            self.metrics.ended_by = "stability"
                            return
                    else:
                        stable_since = 0
            
            # Stall detection: only during active streaming, and only as fallback when UI signals not reliable
            use_stall = strategy != "ui_signals" and (strategy != "hybrid" or not has_ui_signals)
            if use_stall and streaming_active and self._first_token_received and self._stall_start is None:
                time_since_mutation = now - self._last_mutation_time
                if time_since_mutation >= self._stall_threshold:
                    self._stall_start = now - self._stall_threshold
                    self.metrics.stall_count += 1
                    self.events.append(StreamEvent(
                        timestamp=now,
                        event_type="stall_start",
                        details={"stall_threshold_ms": self._stall_threshold * 1000}
                    ))
            
            # Stall recovery
            if not streaming_active and self._stall_start is not None:
                stall_duration = now - self._stall_start
                self.metrics.stall_durations.append(stall_duration)
                self.events.append(StreamEvent(
                    timestamp=now,
                    event_type="stall_end",
                    details={"stall_duration_ms": stall_duration * 1000}
                ))
                self._stall_start = None
        
        # Timeout
        self.metrics.ended_by = "timeout"
        self.metrics.error = f"Timeout after {timeout}s"

    async def _check_ui_signals(self) -> Dict[str, Any]:
        """Check UI signals (stop, copy, busy indicators)."""
        return await self.page.evaluate(
            """([stop, copy, busy]) => window.__streamObserver.checkUISignals(stop, copy, busy)""",
            [self.stop_selector, self.copy_selector, self.busy_selector]
        )

    def _should_stop_by_ui(self, signals: Dict[str, Any]) -> bool:
        """Determine if streaming should stop based on UI signals."""
        # Stop button visible = definitely still generating (highest priority)
        if signals.get("stopVisible") is True:
            return False
        # Stop button hidden + copy button visible = done
        if signals.get("stopVisible") is False and signals.get("copyVisible") is True:
            return True
        # Busy false + copy visible = done (but only if stop is not visible)
        if signals.get("busy") is False and signals.get("copyVisible") is True:
            return True
        return False

    async def _cleanup_observer(self) -> None:
        """Clean up MutationObserver."""
        try:
            await self.page.evaluate("() => window.__streamObserver.disconnect()")
        except Exception:
            pass

    def get_metrics_dict(self) -> Dict[str, Any]:
        """Get metrics as dictionary."""
        return asdict(self.metrics)

    def get_events_dict(self) -> List[Dict[str, Any]]:
        """Get events as list of dictionaries."""
        return [asdict(e) for e in self.events]


async def run_watch(
    url: str,
    profile_name: str = "default",
    headless: bool = False,
    browser_path: Optional[str] = None,
    container_selector: Optional[str] = None,
    assistant_selector: Optional[str] = None,
    stop_selector: Optional[str] = None,
    copy_selector: Optional[str] = None,
    busy_selector: Optional[str] = None,
    strategy: str = "hybrid",
    timeout: float = 120.0,
    send_message: Optional[str] = None,
    input_selector: Optional[str] = None,
    button_selector: Optional[str] = None,
) -> Dict[str, Any]:
    """Run streaming observation test."""
    from .browser import BrowserManager, get_browser_path
    from .send import MessageSender

    if browser_path is None:
        browser_path = await get_browser_path()

    manager = BrowserManager(profile_name, headless)
    page = await manager.start(browser_path)

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        # Enable test mode
        await page.evaluate("setTestMode(true)")

        # Send message if requested
        if send_message:
            sender = MessageSender(page)
            input_sel = input_selector or 'textarea[data-testid="prompt-textarea"]'
            btn_sel = button_selector or '[data-testid="send-button"]'
            await sender.send_textarea_fill(send_message, input_sel, btn_sel)
            await asyncio.sleep(0.5)

        # Default selectors
        container_sel = container_selector or '[role="log"]'
        assistant_sel = assistant_selector or '[data-testid*="assistant"]'
        stop_sel = stop_selector or '[data-testid="stop-button"]'
        copy_sel = copy_selector or '[data-testid="copy-button"]'
        busy_sel = busy_selector or '[data-testid="busy-indicator"]'

        # Start observation
        observer = StreamObserver(
            page, container_sel, assistant_sel,
            stop_sel, copy_sel, busy_sel
        )
        metrics = await observer.start(strategy=strategy, timeout=timeout)

        return {
            "url": url,
            "profile": profile_name,
            "strategy": strategy,
            "metrics": observer.get_metrics_dict(),
            "events": observer.get_events_dict(),
        }
    finally:
        await manager.close()