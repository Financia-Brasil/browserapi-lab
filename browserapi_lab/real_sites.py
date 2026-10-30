"""Real site testing module for browserapi-lab (Phase 8)."""
import asyncio
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional
from playwright.async_api import Page


@dataclass
class SiteTestResult:
    """Results for a single site test."""
    site_name: str
    url: str
    profile: str
    timestamp: float
    inspect: Optional[Dict[str, Any]] = None
    send: Optional[Dict[str, Any]] = None
    watch: Optional[Dict[str, Any]] = None
    extract: Optional[Dict[str, Any]] = None
    session_check: Optional[Dict[str, Any]] = None
    errors: List[str] = None
    status: str = "pending"  # pending, running, completed, failed

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class RealSiteTester:
    """Runs automated tests on real AI chat sites with manual login step."""

    def __init__(self, results_dir: Path):
        self.results_dir = results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.site_results: List[SiteTestResult] = []

    async def test_site(
        self,
        site_name: str,
        url: str,
        profile_name: str,
        headless: bool = False,  # MUST be headed for manual login
        browser_path: Optional[str] = None,
        test_message: str = "Hello, this is a test message from browserapi-lab.",
        wait_for_login: bool = True,
        send_message: bool = True,
        watch_stream: bool = True,
        extract_response: bool = True,
        input_selector: Optional[str] = None,
        button_selector: Optional[str] = None,
        assistant_selector: Optional[str] = None,
        container_selector: Optional[str] = None,
    ) -> SiteTestResult:
        """Run full test suite on a real site."""
        from .browser import BrowserManager, get_browser_path
        from .session import SessionManager

        if browser_path is None:
            browser_path = await get_browser_path()

        result = SiteTestResult(
            site_name=site_name,
            url=url,
            profile=profile_name,
            timestamp=time.time()
        )
        self.site_results.append(result)
        result.status = "running"

        manager = BrowserManager(profile_name, headless)
        page = None

        try:
            print(f"\n{'='*60}")
            print(f"Testing: {site_name} ({url})")
            print(f"Profile: {profile_name}")
            print(f"{'='*60}")

            # Start browser
            page = await manager.start(browser_path)
            print(f"Browser started. Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")

            # MANUAL LOGIN STEP
            if wait_for_login:
                print(f"\n⚠️  MANUAL STEP REQUIRED")
                print(f"Please log in to {site_name} and select the desired model.")
                print(f"Press ENTER in this terminal when ready to continue...")
                await asyncio.get_event_loop().run_in_executor(None, input, "")

            # Session check (use existing page)
            print("\n--- Session Check ---")
            try:
                from .session import SessionManager
                session_mgr = SessionManager()
                session_result = await session_mgr.check_session_validity(page, expected_url_contains=url)
                result.session_check = session_result
                print(f"Session valid: {session_result.get('valid')}")
            except Exception as e:
                result.errors.append(f"session_check: {e}")
                print(f"Session check failed: {e}")

            # Inspect (using existing page)
            print("\n--- Inspect ---")
            try:
                from .discover import discover_all
                inspect_result = await discover_all(page)
                result.inspect = {
                    "url": url,
                    "profile": profile_name,
                    "candidates": inspect_result,
                    "page_title": await page.title(),
                    "page_url": page.url,
                }
                print(f"Found candidates for {len(inspect_result)} element types")
            except Exception as e:
                result.errors.append(f"inspect: {e}")
                print(f"Inspect failed: {e}")

            # Send (using existing page)
            if send_message:
                print("\n--- Send Test ---")
                try:
                    from .send import MessageSender
                    sender = MessageSender(page)
                    # Use default selectors for fixture
                    input_sel = input_selector or 'textarea[data-testid="prompt-textarea"]'
                    btn_sel = button_selector or '[data-testid="send-button"]'
                    sender_results = await sender.run_all_comparison(test_message, input_sel, btn_sel, "textarea")
                    # Also test input and contenteditable
                    # Switch to input
                    await page.evaluate('''() => { document.querySelector('input[value="input"]').click(); }''')
                    await asyncio.sleep(0.2)
                    sender_results.extend(await sender.run_all_comparison(test_message, 'input[data-testid="prompt-input"]', btn_sel, "input"))
                    # Switch to contenteditable
                    await page.evaluate('''() => { document.querySelector('input[value="contenteditable"]').click(); }''')
                    await asyncio.sleep(0.2)
                    sender_results.extend(await sender.run_all_comparison(test_message, '[contenteditable][data-testid="prompt-contenteditable"]', btn_sel, "contenteditable"))
                    
                    from .send import summarize_results
                    send_result = {
                        "url": url,
                        "text": test_message,
                        "profile": profile_name,
                        "results": [r.__dict__ if hasattr(r, '__dict__') else r for r in sender_results],
                        "summary": summarize_results(sender_results)
                    }
                    result.send = send_result
                    summary = send_result.get("summary", {})
                    print(f"Send: {summary.get('passed', 0)}/{summary.get('total_tests', 0)} passed")
                    for itype, method in summary.get("best_method_per_type", {}).items():
                        print(f"  Best {itype}: {method}")
                except Exception as e:
                    result.errors.append(f"send: {e}")
                    print(f"Send failed: {e}")

            # Watch (using existing page)
            if watch_stream and send_message:
                print("\n--- Watch (Streaming) ---")
                try:
                    from .observe import StreamObserver
                    container_sel = container_selector or '[role="log"]'
                    assistant_sel = assistant_selector or '[data-testid*="assistant"]'
                    stop_sel = '[data-testid="stop-button"]'
                    copy_sel = '[data-testid="copy-button"]'
                    busy_sel = '[data-testid="busy-indicator"]'
                    
                    observer = StreamObserver(page, container_sel, assistant_sel, stop_sel, copy_sel, busy_sel)
                    await observer._inject_observer()
                    metrics = await observer.start(strategy="hybrid", timeout=120.0)
                    
                    result.watch = {
                        "url": url,
                        "profile": profile_name,
                        "strategy": "hybrid",
                        "metrics": metrics.__dict__ if hasattr(metrics, '__dict__') else metrics,
                        "events": [e.__dict__ if hasattr(e, '__dict__') else e for e in observer.events],
                    }
                    m = result.watch.get("metrics", {})
                    print(f"TTFT: {m.get('ttft_ms', 'N/A')}ms")
                    print(f"Duration: {m.get('total_duration_ms', 'N/A')}ms")
                    print(f"Ended by: {m.get('ended_by', 'N/A')}")
                except Exception as e:
                    result.errors.append(f"watch: {e}")
                    print(f"Watch failed: {e}")

            # Extract (using existing page)
            if extract_response:
                print("\n--- Extract ---")
                try:
                    from .extract import ResponseExtractor
                    extractor = ResponseExtractor(page)
                    container_sel = container_selector or '[role="log"]'
                    assistant_sel = assistant_selector or '[data-testid*="assistant"]'
                    extract_results = await extractor.extract_all_methods(assistant_sel, container_sel)
                    result.extract = {
                        "url": url,
                        "profile": profile_name,
                        "format": "markdown_like",
                        "comparison": {k: v.__dict__ if hasattr(v, '__dict__') else v for k, v in extract_results.items()},
                    }
                    if "comparison" in result.extract:
                        for method, data in result.extract["comparison"].items():
                            print(f"  {method}: {data['length']} chars, {data['duration_ms']:.1f}ms")
                except Exception as e:
                    result.errors.append(f"extract: {e}")
                    print(f"Extract failed: {e}")

            result.status = "completed" if not result.errors else "completed_with_errors"
            print(f"\n✅ {site_name} test completed")

        except Exception as e:
            result.status = "failed"
            result.errors.append(f"fatal: {e}")
            print(f"\n❌ {site_name} test failed: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await manager.close()

        return result

    async def run_all_sites(self, sites: List[Dict[str, Any]]) -> List[SiteTestResult]:
        """Run tests on multiple sites sequentially."""
        for site in sites:
            # Map profile -> profile_name
            kwargs = site.copy()
            if "profile" in kwargs:
                kwargs["profile_name"] = kwargs.pop("profile")
            await self.test_site(**kwargs)
            # Small delay between sites
            await asyncio.sleep(2)
        return self.site_results

    def generate_report(self, output_path: Optional[Path] = None) -> Path:
        """Generate markdown report from all site results."""
        if output_path is None:
            output_path = self.results_dir / f"FINAL_REPORT_{int(time.time())}.md"

        lines = []
        lines.append("# browserapi-lab — Final Report")
        lines.append(f"\nGenerated: {time.ctime()}")
        lines.append(f"Total sites tested: {len(self.site_results)}")
        lines.append(f"Completed: {sum(1 for r in self.site_results if r.status == 'completed')}")
        lines.append(f"With errors: {sum(1 for r in self.site_results if r.status == 'completed_with_errors')}")
        lines.append(f"Failed: {sum(1 for r in self.site_results if r.status == 'failed')}")

        # Environment summary
        lines.append("\n## Environment")
        try:
            from .environment import run_doctor
            env = run_doctor()
            lines.append(f"- **Distro**: {env['distro']['name']} ({env['distro']['version']})")
            lines.append(f"- **Python**: {env['python']['version']} ({env['python']['architecture']})")
            lines.append(f"- **RAM**: {env['resources']['ram_gb']} GB")
            lines.append(f"- **CPU**: {env['resources']['cpu_count']} cores — {env['resources']['cpu_model']}")
            lines.append(f"- **Browser**: {env['recommendation']['browser']} ({env['recommendation']['path']})")
            lines.append(f"- **Playwright**: {env['playwright']['version'] if env['playwright']['installed'] else 'Not installed'}")
            lines.append(f"- **Recommendation**: {env['recommendation']['recommended'].upper()}")
        except Exception:
            lines.append("- Environment info unavailable")

        # Benchmark summary
        lines.append("\n## Benchmark Summary (fixture)")
        try:
            benchmark_files = list(self.results_dir.glob("benchmark_*.json"))
            if benchmark_files:
                latest = max(benchmark_files, key=lambda f: f.stat().st_mtime)
                with latest.open() as f:
                    bench = json.load(f)
                lines.append(f"- **File**: {latest.name}")
                for s in bench.get("summaries", []):
                    lines.append(f"  - **{s['strategy']}**: {s['avg_duration_ms']:.0f}ms avg, {s['successful_runs']}/{s['total_runs']} passed, RAM: {s['avg_ram_mb']:.1f}MB")
        except Exception:
            lines.append("- Benchmark data unavailable")

        # Site results matrix
        lines.append("\n## Site Test Matrix")
        lines.append("\n| Site | Status | Inspect | Send | Watch | Extract | Session | Errors |")
        lines.append("|------|--------|---------|------|-------|---------|---------|--------|")
        for r in self.site_results:
            inspect_ok = "✅" if r.inspect else "❌"
            send_ok = "✅" if r.send and r.send.get("summary", {}).get("passed", 0) > 0 else "❌"
            watch_ok = "✅" if r.watch else "❌"
            extract_ok = "✅" if r.extract else "❌"
            session_ok = "✅" if r.session_check and r.session_check.get("valid") else "❌"
            errors = len(r.errors)
            lines.append(f"| {r.site_name} | {r.status} | {inspect_ok} | {send_ok} | {watch_ok} | {extract_ok} | {session_ok} | {errors} |")

        # Detailed site results
        lines.append("\n## Detailed Site Results")
        for r in self.site_results:
            lines.append(f"\n### {r.site_name} ({r.url})")
            lines.append(f"- **Profile**: {r.profile}")
            lines.append(f"- **Status**: {r.status}")
            lines.append(f"- **Timestamp**: {time.ctime(r.timestamp)}")

            if r.inspect:
                lines.append(f"\n#### Inspect")
                candidates = r.inspect.get("candidates", {})
                for elem_type, cands in candidates.items():
                    if cands:
                        top = cands[0]
                        lines.append(f"- **{elem_type}**: {top['selector']} (score: {top['score']:.1f}, stable: {top['stable']})")

            if r.send:
                lines.append(f"\n#### Send")
                summary = r.send.get("summary", {})
                lines.append(f"- Passed: {summary.get('passed', 0)}/{summary.get('total_tests', 0)}")
                for itype, method in summary.get("best_method_per_type", {}).items():
                    lines.append(f"  - {itype}: {method}")

            if r.watch:
                lines.append(f"\n#### Watch")
                m = r.watch.get("metrics", {})
                lines.append(f"- TTFT: {m.get('ttft_ms', 'N/A')}ms")
                lines.append(f"- Duration: {m.get('total_duration_ms', 'N/A')}ms")
                lines.append(f"- Mutations: {m.get('mutation_count', 'N/A')}")
                lines.append(f"- Stalls: {m.get('stall_count', 'N/A')}")
                lines.append(f"- Ended by: {m.get('ended_by', 'N/A')}")

            if r.extract:
                lines.append(f"\n#### Extract")
                if "comparison" in r.extract:
                    for method, data in r.extract["comparison"].items():
                        lines.append(f"- {method}: {data['length']} chars, {data['duration_ms']:.1f}ms")

            if r.session_check:
                lines.append(f"\n#### Session")
                lines.append(f"- Valid: {r.session_check.get('valid')}")
                lines.append(f"- Login form: {r.session_check.get('login_form_detected')}")

            if r.errors:
                lines.append(f"\n#### Errors")
                for err in r.errors:
                    lines.append(f"- {err}")

        # Recommendations
        lines.append("\n## Recommendations for Phase 2 (OpenAI-compatible API)")
        lines.append("\n### Reusable Modules")
        lines.append("- `browser.py`: BrowserManager with persistent profiles, lock files")
        lines.append("- `discover.py`: Element discovery with scoring (adapt selectors per site)")
        lines.append("- `send.py`: Comparative sending (fill/keyboard/Enter per input type)")
        lines.append("- `observe.py`: Streaming observation (MutationObserver + UI signals)")
        lines.append("- `extract.py`: Markdown-like extraction (no external deps)")
        lines.append("- `session.py`: Profile management, storage_state export/import")
        lines.append("- `benchmark.py`: Performance measurement framework")

        lines.append("\n### Required Dependencies")
        lines.append("- `playwright>=1.40` (only external dependency)")
        lines.append("- stdlib: asyncio, json, csv, pathlib, time, subprocess, os")

        lines.append("\n### Architecture Notes")
        lines.append("- Headed mode default for manual login/model selection")
        lines.append("- Persistent profiles via `launch_persistent_context()`")
        lines.append("- Lock files prevent concurrent profile corruption")
        lines.append("- Test mode in fixture for fast CI testing")
        lines.append("- No DOM modification during extraction (clone + clean)")

        # Save report
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n📄 Report saved to: {output_path}")
        return output_path


async def run_real_site_tests(
    sites: List[Dict[str, Any]],
    results_dir: Path = None
) -> List[SiteTestResult]:
    """Convenience function to run real site tests."""
    if results_dir is None:
        results_dir = Path(__file__).parent.parent / "results"

    tester = RealSiteTester(results_dir)
    results = await tester.run_all_sites(sites)
    tester.generate_report()
    return results