"""Response extraction module for browserapi-lab."""
import asyncio
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from playwright.async_api import Page


@dataclass
class ExtractResult:
    """Result of extraction."""
    text: str
    format: str
    length: int
    duration_ms: float
    method: str


class ResponseExtractor:
    """Extracts assistant responses without modifying real DOM."""

    def __init__(self, page: Page):
        self.page = page

    async def extract_last_assistant(
        self,
        assistant_selector: str = '[data-testid*="assistant"]',
        format: str = "markdown_like",
        container_selector: str = '[role="log"]'
    ) -> ExtractResult:
        """Extract last assistant message."""
        import time
        start = time.time()

        if format == "clean_text":
            text = await self._extract_clean_text(assistant_selector, container_selector)
        elif format == "markdown_like":
            text = await self._extract_markdown_like(assistant_selector, container_selector)
        else:
            raise ValueError(f"Unknown format: {format}")

        duration = (time.time() - start) * 1000
        return ExtractResult(
            text=text,
            format=format,
            length=len(text),
            duration_ms=duration,
            method=format
        )

    async def _extract_clean_text(
        self,
        assistant_selector: str,
        container_selector: str
    ) -> str:
        """Extract plain text from last assistant message."""
        text = await self.page.evaluate(
            """([assistantSel, containerSel]) => {
                const container = document.querySelector(containerSel);
                if (!container) return '';
                const assistants = container.querySelectorAll(assistantSel);
                if (assistants.length === 0) return '';
                const last = assistants[assistants.length - 1];
                // Get text content, normalize whitespace
                return last.textContent.replace(/\\s+/g, ' ').trim();
            }""",
            [assistant_selector, container_selector]
        )
        return text

    async def _extract_markdown_like(
        self,
        assistant_selector: str,
        container_selector: str
    ) -> str:
        """Extract with markdown-like serialization (clone + clean)."""
        html = await self.page.evaluate(
            """([assistantSel, containerSel]) => {
                const container = document.querySelector(containerSel);
                if (!container) return '';
                const assistants = container.querySelectorAll(assistantSel);
                if (assistants.length === 0) return '';
                const last = assistants[assistants.length - 1];
                // Clone to avoid modifying real DOM
                const clone = last.cloneNode(true);
                return clone.outerHTML;
            }""",
            [assistant_selector, container_selector]
        )

        # Parse and serialize to markdown-like
        return self._html_to_markdown(html)

    def _html_to_markdown(self, html: str) -> str:
        """Convert HTML to markdown-like text."""
        # Parse HTML using regex (no external deps)
        text = html

        # Remove script/style
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Handle code blocks first (before other tags)
        text = self._convert_code_blocks(text)

        # Headings
        text = re.sub(r'<h([1-6])[^>]*>(.*?)</h\1>', self._heading_repl, text, flags=re.DOTALL | re.IGNORECASE)

        # Paragraphs
        text = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', text, flags=re.DOTALL | re.IGNORECASE)

        # Line breaks
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

        # Bold
        text = re.sub(r'<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>', r'**\1**', text, flags=re.DOTALL | re.IGNORECASE)

        # Italic
        text = re.sub(r'<(?:em|i)[^>]*>(.*?)</(?:em|i)>', r'*\1*', text, flags=re.DOTALL | re.IGNORECASE)

        # Inline code
        text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.DOTALL | re.IGNORECASE)

        # Links
        text = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.DOTALL | re.IGNORECASE)

        # Lists
        text = self._convert_lists(text)

        # Blockquotes
        text = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', self._blockquote_repl, text, flags=re.DOTALL | re.IGNORECASE)

        # Tables
        text = self._convert_tables(text)

        # Remove remaining tags
        text = re.sub(r'<[^>]+>', '', text)

        # Decode entities
        text = self._decode_entities(text)

        # Normalize whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        return text

    def _heading_repl(self, match) -> str:
        level = int(match.group(1))
        content = match.group(2).strip()
        content = re.sub(r'<[^>]+>', '', content)
        return '\n' + '#' * level + ' ' + content + '\n\n'

    def _blockquote_repl(self, match) -> str:
        content = match.group(1)
        content = re.sub(r'<[^>]+>', '', content)
        lines = content.strip().split('\n')
        return '\n' + '\n'.join('> ' + line.strip() for line in lines if line.strip()) + '\n\n'

    def _convert_code_blocks(self, text: str) -> str:
        """Convert <pre><code> blocks to markdown fenced code."""
        # Pattern: <pre><code class="language-xxx">content</code></pre>
        def repl(match):
            inner = match.group(1)
            # Extract language from class
            lang_match = re.search(r'class=["\']language-(\w+)["\']', match.group(0), re.IGNORECASE)
            lang = lang_match.group(1) if lang_match else ''
            # Clean inner content
            inner = re.sub(r'<[^>]+>', '', inner)
            inner = self._decode_entities(inner)
            return f'\n```{lang}\n{inner.strip()}\n```\n\n'

        text = re.sub(r'<pre[^>]*><code[^>]*>(.*?)</code></pre>', repl, text, flags=re.DOTALL | re.IGNORECASE)
        # Also handle <pre> without <code>
        text = re.sub(r'<pre[^>]*>(.*?)</pre>', lambda m: f'\n```\n{re.sub(r"<[^>]+>", "", m.group(1)).strip()}\n```\n\n', text, flags=re.DOTALL | re.IGNORECASE)
        return text

    def _convert_lists(self, text: str) -> str:
        """Convert <ul>/<ol> to markdown lists."""
        # Convert unordered lists
        def ul_repl(match):
            items = re.findall(r'<li[^>]*>(.*?)</li>', match.group(1), re.DOTALL | re.IGNORECASE)
            result = []
            for item in items:
                item = re.sub(r'<[^>]+>', '', item)
                item = self._decode_entities(item).strip()
                if item:
                    result.append(f'- {item}')
            return '\n' + '\n'.join(result) + '\n\n'

        text = re.sub(r'<ul[^>]*>(.*?)</ul>', ul_repl, text, flags=re.DOTALL | re.IGNORECASE)

        # Convert ordered lists
        def ol_repl(match):
            items = re.findall(r'<li[^>]*>(.*?)</li>', match.group(1), re.DOTALL | re.IGNORECASE)
            result = []
            for i, item in enumerate(items, 1):
                item = re.sub(r'<[^>]+>', '', item)
                item = self._decode_entities(item).strip()
                if item:
                    result.append(f'{i}. {item}')
            return '\n' + '\n'.join(result) + '\n\n'

        text = re.sub(r'<ol[^>]*>(.*?)</ol>', ol_repl, text, flags=re.DOTALL | re.IGNORECASE)
        return text

    def _convert_tables(self, text: str) -> str:
        """Convert <table> to markdown table."""
        def table_repl(match):
            table_html = match.group(0)
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
            if not rows:
                return ''

            markdown_rows = []
            for i, row in enumerate(rows):
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
                if not cells:
                    continue
                clean_cells = []
                for cell in cells:
                    cell = re.sub(r'<[^>]+>', '', cell)
                    cell = self._decode_entities(cell).strip()
                    cell = cell.replace('|', '\\|')  # Escape pipes
                    clean_cells.append(cell)
                markdown_rows.append('| ' + ' | '.join(clean_cells) + ' |')

                # Add separator after header row
                if i == 0:
                    markdown_rows.append('| ' + ' | '.join('---' for _ in clean_cells) + ' |')

            return '\n' + '\n'.join(markdown_rows) + '\n\n'

        text = re.sub(r'<table[^>]*>.*?</table>', table_repl, text, flags=re.DOTALL | re.IGNORECASE)
        return text

    def _decode_entities(self, text: str) -> str:
        """Decode common HTML entities."""
        entities = {
            '&nbsp;': ' ',
            '&': '&',
            '<': '<',
            '>': '>',
            '"': '"',
            '&rsquo;': "'",
            '&apos;': "'",
            '&ndash;': '\u2013',
            '&mdash;': '\u2014',
            '&hellip;': '\u2026',
        }
        for entity, char in entities.items():
            text = text.replace(entity, char)
        # Numeric entities
        text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
        text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
        return text

    async def extract_all_methods(
        self,
        assistant_selector: str = '[data-testid*="assistant"]',
        container_selector: str = '[role="log"]'
    ) -> Dict[str, ExtractResult]:
        """Extract using all methods for comparison."""
        results = {}
        for fmt in ["clean_text", "markdown_like"]:
            results[fmt] = await self.extract_last_assistant(assistant_selector, fmt, container_selector)
        # Also get raw innerText and textContent for comparison
        results["innerText"] = await self._extract_raw("innerText", assistant_selector, container_selector)
        results["textContent"] = await self._extract_raw("textContent", assistant_selector, container_selector)
        return results

    async def _extract_raw(
        self,
        prop: str,
        assistant_selector: str,
        container_selector: str
    ) -> ExtractResult:
        """Extract raw innerText or textContent."""
        import time
        start = time.time()
        text = await self.page.evaluate(
            f"""([assistantSel, containerSel]) => {{
                const container = document.querySelector(containerSel);
                if (!container) return '';
                const assistants = container.querySelectorAll(assistantSel);
                if (assistants.length === 0) return '';
                return assistants[assistants.length - 1].{prop};
            }}""",
            [assistant_selector, container_selector]
        )
        duration = (time.time() - start) * 1000
        return ExtractResult(
            text=text,
            format=prop,
            length=len(text),
            duration_ms=duration,
            method=prop
        )


async def run_extract(
    url: str,
    profile_name: str = "default",
    headless: bool = False,
    browser_path: Optional[str] = None,
    format: str = "markdown_like",
    assistant_selector: Optional[str] = None,
    container_selector: Optional[str] = None,
    send_message: Optional[str] = None,
    input_selector: Optional[str] = None,
    button_selector: Optional[str] = None,
    compare: bool = False
) -> Dict[str, Any]:
    """Run extraction test."""
    from .browser import BrowserManager, get_browser_path
    from .send import MessageSender

    if browser_path is None:
        browser_path = await get_browser_path()

    manager = BrowserManager(profile_name, headless)
    page = await manager.start(browser_path)

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")
        await page.evaluate("setTestMode(true)")

        # Send message if requested
        if send_message:
            sender = MessageSender(page)
            input_sel = input_selector or 'textarea[data-testid="prompt-textarea"]'
            btn_sel = button_selector or '[data-testid="send-button"]'
            await sender.send_textarea_fill(send_message, input_sel, btn_sel)
            # Wait for streaming to complete (input enabled)
            for _ in range(300):
                disabled = await page.locator(input_sel).evaluate('el => el.disabled')
                if not disabled:
                    break
                await asyncio.sleep(0.1)

        extractor = ResponseExtractor(page)

        ass_sel = assistant_selector or '[data-testid*="assistant"]'
        cont_sel = container_selector or '[role="log"]'

        if compare:
            results = await extractor.extract_all_methods(ass_sel, cont_sel)
            return {
                "url": url,
                "profile": profile_name,
                "format": format,
                "comparison": {k: asdict(v) for k, v in results.items()}
            }
        else:
            result = await extractor.extract_last_assistant(ass_sel, format, cont_sel)
            return {
                "url": url,
                "profile": profile_name,
                "format": format,
                "result": asdict(result)
            }
    finally:
        await manager.close()