"""Element discovery module for browserapi-lab."""
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from playwright.async_api import Page, ElementHandle, Locator


@dataclass
class Candidate:
    """Represents a candidate element with scoring."""
    selector: str
    selector_type: str  # "css", "playwright", "xpath"
    role: str
    tag_name: str
    attributes: Dict[str, str]
    score: float
    reasons: List[str]
    match_count: int
    snippet: str
    visible: bool
    stable: bool


# Selector patterns for different element types
SELECTOR_STRATEGIES = {
    "prompt_input": [
        # Priority: testid > aria > semantic > placeholder > type > generic
        ('[data-testid*="prompt"]', "testid", 100),
        ('[data-testid*="input"]', "testid", 90),
        ('[data-testid*="message"]', "testid", 80),
        ('[data-testid*="composer"]', "testid", 80),
        ('[data-testid*="editor"]', "testid", 80),
        ('textarea[placeholder*="message"]', "placeholder", 75),
        ('textarea[placeholder*="chat"]', "placeholder", 70),
        ('textarea[placeholder*="ask"]', "placeholder", 70),
        ('textarea[placeholder*="type"]', "placeholder", 65),
        ('textarea[aria-label*="message"]', "aria", 75),
        ('textarea[aria-label*="chat"]', "aria", 70),
        ('textarea[aria-label*="prompt"]', "aria", 70),
        ('input[type="text"][placeholder*="message"]', "placeholder", 70),
        ('input[type="text"][placeholder*="chat"]', "placeholder", 65),
        ('input[type="text"][aria-label*="message"]', "aria", 70),
        ('[contenteditable="true"][role="textbox"]', "semantic", 85),
        ('[contenteditable="true"][data-testid*="prompt"]', "testid", 90),
        ('[contenteditable="true"][aria-label*="message"]', "aria", 80),
        ('textarea', "generic", 40),
        ('input[type="text"]', "generic", 35),
        ('[contenteditable="true"]', "generic", 30),
    ],
    "send_button": [
        ('[data-testid*="send"]', "testid", 100),
        ('[data-testid*="submit"]', "testid", 90),
        ('button[aria-label*="send"]', "aria", 85),
        ('button[aria-label*="submit"]', "aria", 80),
        ('button[type="submit"]', "semantic", 70),
        ('button:has-text("Send")', "text", 65),
        ('button:has-text("Enviar")', "text", 65),
        ('button:has-text("Submit")', "text", 60),
        ('button.send-btn', "class", 50),
        ('button[class*="send"]', "class", 45),
        ('button[class*="submit"]', "class", 45),
    ],
    "conversation_container": [
        ('[data-testid*="conversation"]', "testid", 100),
        ('[data-testid*="messages"]', "testid", 95),
        ('[data-testid*="chat"]', "testid", 90),
        ('[role="log"]', "semantic", 85),
        ('[aria-live="polite"]', "aria", 80),
        ('[class*="messages"]', "class", 60),
        ('[class*="conversation"]', "class", 55),
        ('[class*="chat"]', "class", 50),
        ('main', "semantic", 40),
    ],
    "assistant_messages": [
        ('[data-testid*="assistant"]', "testid", 100),
        ('[data-testid*="model"]', "testid", 90),
        ('[data-testid*="response"]', "testid", 85),
        ('[role="article"][class*="assistant"]', "semantic", 80),
        ('[class*="assistant"]', "class", 60),
        ('[class*="model"]', "class", 55),
        ('[class*="response"]', "class", 50),
        ('[class*="message"][class*="bot"]', "class", 45),
    ],
    "stop_indicator": [
        ('[data-testid*="stop"]', "testid", 100),
        ('[data-testid*="cancel"]', "testid", 90),
        ('button[aria-label*="stop"]', "aria", 85),
        ('button[aria-label*="cancel"]', "aria", 80),
        ('[class*="stop"]', "class", 50),
        ('[class*="cancel"]', "class", 45),
    ],
    "copy_indicator": [
        ('[data-testid*="copy"]', "testid", 100),
        ('button[aria-label*="copy"]', "aria", 90),
        ('[class*="copy"]', "class", 50),
    ],
    "busy_indicator": [
        ('[aria-busy="true"]', "aria", 100),
        ('[data-testid*="busy"]', "testid", 95),
        ('[data-testid*="loading"]', "testid", 90),
        ('[data-testid*="generating"]', "testid", 90),
        ('[class*="busy"]', "class", 50),
        ('[class*="loading"]', "class", 45),
        ('[class*="streaming"]', "class", 40),
        ('[class*="typing"]', "class", 40),
    ],
}


DYNAMIC_CLASS_PATTERNS = [
    r'^[a-z]{2,3}-[a-z0-9]{8,}',  # css-in-js: abc-def12345
    r'^[A-Z][a-z]+[A-Z][a-z]+\d*$',  # PascalCase components
    r'^css-\w+-\w+',  # emotion/styled-components
    r'^\w+__\w+--\w+',  # BEM modifiers
    r'^sc-[a-z0-9]+',  # styled-components
    r'^Mui\w+',  # MUI
    r'^\w+-[a-f0-9]{6,}',  # hash suffixes
]


def is_dynamic_class(class_name: str) -> bool:
    """Check if a class name looks dynamically generated."""
    for pattern in DYNAMIC_CLASS_PATTERNS:
        if re.match(pattern, class_name):
            return True
    return False


def score_selector(selector: str, match_count: int, attributes: Dict[str, str]) -> tuple[float, List[str]]:
    """Score a selector based on stability and specificity."""
    score = 0.0
    reasons = []

    # Test IDs are gold standard
    if "[data-testid" in selector:
        score += 50
        reasons.append("data-testid present")

    # ARIA attributes are excellent
    if "aria-" in selector:
        score += 30
        reasons.append("ARIA attribute")

    # Role is good
    if "[role=" in selector:
        score += 20
        reasons.append("role attribute")

    # Placeholder is decent
    if "placeholder" in selector:
        score += 15
        reasons.append("placeholder")

    # Semantic HTML
    if any(tag in selector for tag in ["textarea", "button[type=", "input[type="]):
        score += 10
        reasons.append("semantic element")

    # Classes - check if dynamic
    class_matches = re.findall(r'\.([a-zA-Z][\w-]*)', selector)
    dynamic_classes = [c for c in class_matches if is_dynamic_class(c)]
    stable_classes = [c for c in class_matches if not is_dynamic_class(c)]

    if dynamic_classes:
        score -= 20 * len(dynamic_classes)
        reasons.append(f"dynamic classes: {dynamic_classes}")
    if stable_classes:
        score += 5 * len(stable_classes)
        reasons.append(f"stable classes: {stable_classes}")

    # Penalize nth-child, nth-of-type
    if "nth-child" in selector or "nth-of-type" in selector:
        score -= 30
        reasons.append("uses nth-child")

    # Penalize long paths
    depth = selector.count(" > ") + selector.count(" ") + 1
    if depth > 5:
        score -= (depth - 5) * 5
        reasons.append(f"deep selector (depth={depth})")

    # Match count penalty (too many = not specific enough)
    if match_count > 1:
        score -= min(match_count * 5, 30)
        reasons.append(f"matches {match_count} elements")

    # Attribute bonuses
    for attr in ["id", "name", "data-testid", "aria-label", "role"]:
        if attr in attributes:
            score += 10
            reasons.append(f"has {attr}")

    return max(score, 0), reasons


async def find_candidates(page: Page, element_type: str) -> List[Candidate]:
    """Find and rank candidate elements for a given type."""
    strategies = SELECTOR_STRATEGIES.get(element_type, [])
    all_candidates = []

    for selector, selector_type, base_score in strategies:
        try:
            # Use page.locator for counting
            locator = page.locator(selector)
            count = await locator.count()

            if count == 0:
                continue

            # Get first match for inspection
            elements = await locator.element_handles()
            for el in elements[:3]:  # Inspect up to 3 matches
                candidate = await analyze_element(el, selector, selector_type, count, page, element_type)
                all_candidates.append(candidate)

        except Exception:
            continue

    # Deduplicate by selector
    seen = set()
    unique = []
    for c in all_candidates:
        key = (c.selector, c.selector_type)
        if key not in seen:
            seen.add(key)
            unique.append(c)

    # Sort by score descending
    unique.sort(key=lambda x: x.score, reverse=True)
    return unique


async def analyze_element(
    element: ElementHandle,
    selector: str,
    selector_type: str,
    match_count: int,
    page: Page,
    element_type: str
) -> Candidate:
    """Analyze a single element for attributes and visibility."""
    # Get tag name
    tag_name = await element.evaluate("el => el.tagName.toLowerCase()")

    # Get attributes
    attributes = await element.evaluate("""el => {
        const attrs = {};
        for (const attr of el.attributes) {
            attrs[attr.name] = attr.value;
        }
        return attrs;
    }""")

    # Check visibility
    visible = await element.is_visible()

    # Get snippet
    snippet = await element.evaluate("""el => {
        const clone = el.cloneNode(true);
        clone.innerHTML = '';
        return clone.outerHTML.slice(0, 200);
    }""")

    # Determine role from element type
    role = element_type.replace("_", " ")

    # Score it
    score, reasons = score_selector(selector, match_count, attributes)

    # Stability heuristic
    stable = (
        "[data-testid" in selector or
        "aria-" in selector or
        "[role=" in selector or
        "placeholder" in selector or
        (tag_name in ["textarea", "button", "input"] and not any(is_dynamic_class(c) for c in attributes.get("class", "").split()))
    )

    return Candidate(
        selector=selector,
        selector_type=selector_type,
        role=role,
        tag_name=tag_name,
        attributes=attributes,
        score=score,
        reasons=reasons,
        match_count=match_count,
        snippet=snippet,
        visible=visible,
        stable=stable
    )


async def discover_all(page: Page) -> Dict[str, List[Dict[str, Any]]]:
    """Discover all element types on the page."""
    results = {}
    for element_type in SELECTOR_STRATEGIES.keys():
        candidates = await find_candidates(page, element_type)
        results[element_type] = [asdict(c) for c in candidates[:10]]  # Top 10
    return results


async def run_inspect(url: str, profile_name: str = "default", headless: bool = False, browser_path: Optional[str] = None) -> Dict[str, Any]:
    """Run full inspection on a URL."""
    from .browser import BrowserManager, get_browser_path

    if browser_path is None:
        browser_path = await get_browser_path()

    manager = BrowserManager(profile_name, headless)
    page = await manager.start(browser_path)

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        results = await discover_all(page)

        return {
            "url": url,
            "profile": profile_name,
            "candidates": results,
            "page_title": await page.title(),
            "page_url": page.url,
        }
    finally:
        await manager.close()