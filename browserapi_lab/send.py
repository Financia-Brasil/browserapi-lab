"""Message sending module for browserapi-lab."""
import asyncio
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from playwright.async_api import Page, ElementHandle


@dataclass
class SendResult:
    """Result of a send attempt."""
    method: str
    input_type: str
    success: bool
    duration_ms: float
    error: Optional[str] = None
    dom_changed: bool = False
    user_message_visible: bool = False


class MessageSender:
    """Comparative message sending across input types."""

    def __init__(self, page: Page):
        self.page = page
        self.results: List[SendResult] = []

    async def find_input(self, selector: str) -> Optional[ElementHandle]:
        """Find input element by selector."""
        try:
            locator = self.page.locator(selector)
            if await locator.count() > 0:
                return await locator.element_handle()
        except Exception:
            pass
        return None

    async def find_send_button(self, selector: str) -> Optional[ElementHandle]:
        """Find send button by selector."""
        try:
            locator = self.page.locator(selector)
            if await locator.count() > 0:
                return await locator.element_handle()
        except Exception:
            pass
        return None

    async def wait_for_user_message(self, timeout: float = 5.0) -> bool:
        """Wait for user message to appear in DOM."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                count = await self.page.locator('[data-testid="user-message"]').count()
                if count > 0:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.1)
        return False

    async def wait_for_input_ready(self, input_sel: str, timeout: float = 30.0) -> bool:
        """Wait for input to be enabled (not disabled)."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                disabled = await self.page.locator(input_sel).evaluate('el => el.disabled')
                if not disabled:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.1)
        return False

    # ===== TEXTAREA METHODS =====

    async def send_textarea_fill(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via textarea fill()."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)
            btn_el = await self.find_send_button(btn_sel)

            if not input_el:
                return SendResult("fill", "textarea", False, (time.time()-start)*1000, "Input not found")

            await input_el.fill(text)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("fill", "textarea", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("fill", "textarea", False, (time.time()-start)*1000, str(e))

    async def send_textarea_press(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via textarea press_sequentially()."""
        start = time.time()
        try:
            btn_el = await self.find_send_button(btn_sel)

            if not btn_el:
                return SendResult("press_sequentially", "textarea", False, (time.time()-start)*1000, "Button not found")

            await self.page.locator(input_sel).click()
            await self.page.locator(input_sel).press_sequentially(text, delay=10)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("press_sequentially", "textarea", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("press_sequentially", "textarea", False, (time.time()-start)*1000, str(e))

    async def send_textarea_keyboard(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via real keyboard events."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)
            btn_el = await self.find_send_button(btn_sel)

            if not input_el:
                return SendResult("keyboard", "textarea", False, (time.time()-start)*1000, "Input not found")

            await input_el.click()
            await self.page.keyboard.type(text, delay=10)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("keyboard", "textarea", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("keyboard", "textarea", False, (time.time()-start)*1000, str(e))

    async def send_textarea_enter(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via textarea + Enter key (no button click)."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)

            if not input_el:
                return SendResult("enter_key", "textarea", False, (time.time()-start)*1000, "Input not found")

            await input_el.fill(text)
            await input_el.press("Enter")

            dom_changed = await self.wait_for_user_message()
            return SendResult("enter_key", "textarea", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("enter_key", "textarea", False, (time.time()-start)*1000, str(e))

    # ===== INPUT TYPE=TEXT METHODS =====

    async def send_input_fill(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via input fill()."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)
            btn_el = await self.find_send_button(btn_sel)

            if not input_el:
                return SendResult("fill", "input", False, (time.time()-start)*1000, "Input not found")

            await input_el.fill(text)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("fill", "input", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("fill", "input", False, (time.time()-start)*1000, str(e))

    async def send_input_press(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via input press_sequentially()."""
        start = time.time()
        try:
            btn_el = await self.find_send_button(btn_sel)

            if not btn_el:
                return SendResult("press_sequentially", "input", False, (time.time()-start)*1000, "Button not found")

            await self.page.locator(input_sel).click()
            await self.page.locator(input_sel).press_sequentially(text, delay=10)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("press_sequentially", "input", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("press_sequentially", "input", False, (time.time()-start)*1000, str(e))

    async def send_input_keyboard(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via input + real keyboard."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)
            btn_el = await self.find_send_button(btn_sel)

            if not input_el:
                return SendResult("keyboard", "input", False, (time.time()-start)*1000, "Input not found")

            await input_el.click()
            await self.page.keyboard.type(text, delay=10)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("keyboard", "input", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("keyboard", "input", False, (time.time()-start)*1000, str(e))

    async def send_input_enter(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via input + Enter key."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)

            if not input_el:
                return SendResult("enter_key", "input", False, (time.time()-start)*1000, "Input not found")

            await input_el.fill(text)
            await input_el.press("Enter")

            dom_changed = await self.wait_for_user_message()
            return SendResult("enter_key", "input", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("enter_key", "input", False, (time.time()-start)*1000, str(e))

    # ===== CONTENTEDITABLE METHODS =====

    async def send_ce_fill(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via contenteditable innerText + button click."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)
            btn_el = await self.find_send_button(btn_sel)

            if not input_el:
                return SendResult("innerText", "contenteditable", False, (time.time()-start)*1000, "Input not found")

            await input_el.fill(text)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("innerText", "contenteditable", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("innerText", "contenteditable", False, (time.time()-start)*1000, str(e))

    async def send_ce_keyboard(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via contenteditable + real keyboard."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)
            btn_el = await self.find_send_button(btn_sel)

            if not input_el:
                return SendResult("keyboard", "contenteditable", False, (time.time()-start)*1000, "Input not found")

            await input_el.click()
            await self.page.keyboard.type(text, delay=10)
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("keyboard", "contenteditable", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("keyboard", "contenteditable", False, (time.time()-start)*1000, str(e))

    async def send_ce_exec_command(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via document.execCommand('insertText')."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)
            btn_el = await self.find_send_button(btn_sel)

            if not input_el:
                return SendResult("execCommand", "contenteditable", False, (time.time()-start)*1000, "Input not found")

            await input_el.click()
            await input_el.focus()
            await self.page.evaluate("""([el, text]) => {
                document.execCommand('insertText', false, text);
            }""", [input_el, text])
            await btn_el.click()

            dom_changed = await self.wait_for_user_message()
            return SendResult("execCommand", "contenteditable", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("execCommand", "contenteditable", False, (time.time()-start)*1000, str(e))

    async def send_ce_enter(self, text: str, input_sel: str, btn_sel: str) -> SendResult:
        """Send via contenteditable + Enter."""
        start = time.time()
        try:
            input_el = await self.find_input(input_sel)

            if not input_el:
                return SendResult("enter_key", "contenteditable", False, (time.time()-start)*1000, "Input not found")

            await input_el.fill(text)
            await input_el.press("Enter")

            dom_changed = await self.wait_for_user_message()
            return SendResult("enter_key", "contenteditable", True, (time.time()-start)*1000, dom_changed=dom_changed, user_message_visible=dom_changed)

        except Exception as e:
            return SendResult("enter_key", "contenteditable", False, (time.time()-start)*1000, str(e))

    async def run_all_comparison(self, text: str, input_sel: str, btn_sel: str, input_type: str) -> List[SendResult]:
        """Run all send methods for a given input type."""
        results = []

        if input_type == "textarea":
            methods = [
                ("fill", self.send_textarea_fill),
                ("press_sequentially", self.send_textarea_press),
                ("keyboard", self.send_textarea_keyboard),
                ("enter_key", self.send_textarea_enter),
            ]
        elif input_type == "input":
            methods = [
                ("fill", self.send_input_fill),
                ("press_sequentially", self.send_input_press),
                ("keyboard", self.send_input_keyboard),
                ("enter_key", self.send_input_enter),
            ]
        elif input_type == "contenteditable":
            methods = [
                ("innerText", self.send_ce_fill),
                ("keyboard", self.send_ce_keyboard),
                ("execCommand", self.send_ce_exec_command),
                ("enter_key", self.send_ce_enter),
            ]
        else:
            return results

        for name, method in methods:
            # Clear any existing user message first
            await self.page.evaluate("""() => {
                const msg = document.querySelector('[data-testid="user-message"]');
                if (msg) msg.remove();
            }""")

            # Wait for input to be ready (enabled) before next send
            await self.wait_for_input_ready(input_sel)

            result = await method(text, input_sel, btn_sel)
            results.append(result)
            self.results.append(result)

            # Small delay between tests
            await asyncio.sleep(0.5)

        return results


async def run_send_test(url: str, text: str, profile_name: str = "default",
                        headless: bool = False, browser_path: Optional[str] = None,
                        input_selector: Optional[str] = None,
                        button_selector: Optional[str] = None) -> Dict[str, Any]:
    """Run comparative send tests."""
    from .browser import BrowserManager, get_browser_path

    if browser_path is None:
        browser_path = await get_browser_path()

    manager = BrowserManager(profile_name, headless)
    page = await manager.start(browser_path)

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        # Enable test mode for fast, reliable testing
        await page.evaluate("setTestMode(true)")

        sender = MessageSender(page)

        # Use provided selectors or defaults
        input_sel = input_selector or '[data-testid*="prompt"]'
        btn_sel = button_selector or '[data-testid*="send"]'

        # Test each input type
        all_results = []

        # Textarea
        await sender.run_all_comparison(text, 'textarea[data-testid="prompt-textarea"]', btn_sel, "textarea")
        all_results.extend(sender.results[-4:])

        # Input (switch to it first)
        await page.evaluate("""() => {
            document.querySelector('input[value="input"]').click();
        }""")
        await asyncio.sleep(0.2)
        await sender.run_all_comparison(text, 'input[data-testid="prompt-input"]', btn_sel, "input")
        all_results.extend(sender.results[-4:])

        # ContentEditable (switch to it)
        await page.evaluate("""() => {
            document.querySelector('input[value="contenteditable"]').click();
        }""")
        await asyncio.sleep(0.2)
        await sender.run_all_comparison(text, '[contenteditable][data-testid="prompt-contenteditable"]', btn_sel, "contenteditable")
        all_results.extend(sender.results[-4:])

        return {
            "url": url,
            "text": text,
            "profile": profile_name,
            "input_selector": input_sel,
            "button_selector": btn_sel,
            "results": [asdict(r) for r in all_results],
            "summary": summarize_results(all_results)
        }
    finally:
        await manager.close()


def summarize_results(results: List[SendResult]) -> Dict[str, Any]:
    """Summarize send results by input type and method."""
    by_type = {}
    for r in results:
        if r.input_type not in by_type:
            by_type[r.input_type] = {}
        by_type[r.input_type][r.method] = {
            "success": r.success,
            "duration_ms": r.duration_ms,
            "error": r.error,
            "dom_changed": r.dom_changed
        }

    # Best method per type
    best = {}
    for itype, methods in by_type.items():
        successful = [(m, d) for m, d in methods.items() if d["success"]]
        if successful:
            best[itype] = min(successful, key=lambda x: x[1]["duration_ms"])[0]
        else:
            best[itype] = None

    return {
        "by_type": by_type,
        "best_method_per_type": best,
        "total_tests": len(results),
        "passed": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success)
    }