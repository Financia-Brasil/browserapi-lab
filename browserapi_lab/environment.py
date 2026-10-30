"""Environment audit module for browserapi-lab."""
import os
import platform
import subprocess
import sys
import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List


def get_linux_distro() -> Dict[str, str]:
    """Detect Linux distribution and version."""
    distro_info = {"name": "unknown", "version": "unknown", "id": "unknown"}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    distro_info["name"] = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("VERSION_ID="):
                    distro_info["version"] = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("ID=") and "ID_LIKE" not in line:
                    distro_info["id"] = line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return distro_info


def get_python_info() -> Dict[str, Any]:
    """Get Python version and architecture info."""
    return {
        "version": sys.version.split()[0],
        "executable": sys.executable,
        "architecture": platform.architecture()[0],
        "platform": platform.platform(),
    }


def get_system_resources() -> Dict[str, Any]:
    """Get RAM and CPU info."""
    info = {"ram_gb": 0, "cpu_count": 0, "cpu_model": "unknown"}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    info["ram_gb"] = round(kb / 1024 / 1024, 2)
                    break
    except FileNotFoundError:
        pass
    try:
        info["cpu_count"] = len(open("/proc/cpuinfo").read().split("processor\t:")) - 1
    except Exception:
        info["cpu_count"] = os.cpu_count() or 0
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu_model"] = line.split(":", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass
    return info


def find_chromium() -> List[Dict[str, Any]]:
    """Find Chrome/Chromium installations."""
    browsers = []
    candidates = [
        ("google-chrome", "Google Chrome"),
        ("google-chrome-stable", "Google Chrome Stable"),
        ("chromium", "Chromium"),
        ("chromium-browser", "Chromium Browser"),
        ("brave-browser", "Brave Browser"),
        ("microsoft-edge", "Microsoft Edge"),
        ("vivaldi", "Vivaldi"),
    ]
    for cmd, name in candidates:
        path = shutil.which(cmd)
        if path:
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                version = result.stdout.strip() or result.stderr.strip()
                browsers.append({
                    "name": name,
                    "command": cmd,
                    "path": path,
                    "version": version,
                    "type": "system"
                })
            except Exception:
                browsers.append({
                    "name": name,
                    "command": cmd,
                    "path": path,
                    "version": "unknown",
                    "type": "system"
                })
    return browsers


def check_playwright() -> Dict[str, Any]:
    """Check Playwright installation and available browsers."""
    result = {
        "installed": False,
        "version": None,
        "browsers": [],
        "install_command": "pip install playwright && playwright install chromium"
    }
    try:
        import playwright
        from importlib.metadata import version as pkg_version
        result["installed"] = True
        result["version"] = pkg_version("playwright")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                for browser_type in ["chromium", "firefox", "webkit"]:
                    browser = getattr(p, browser_type)
                    if browser.executable_path.exists():
                        result["browsers"].append({
                            "name": browser_type,
                            "path": str(browser.executable_path),
                            "type": "playwright-managed"
                        })
        except Exception:
            pass
    except ImportError:
        pass
    return result


def check_headed_support() -> Dict[str, Any]:
    """Check if headed mode is supported."""
    return {
        "display": os.environ.get("DISPLAY", "not set"),
        "wayland": os.environ.get("WAYLAND_DISPLAY", "not set"),
        "x11_forwarding": bool(os.environ.get("SSH_CONNECTION")),
        "recommendation": "headed" if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") else "headless only"
    }


def get_recommendation(browsers: List[Dict], playwright_info: Dict) -> Dict[str, Any]:
    """Generate recommendation based on evidence."""
    system_chromium = [b for b in browsers if b["name"] in ("Chromium", "Chromium Browser", "Google Chrome", "Google Chrome Stable")]
    pw_chromium = [b for b in playwright_info["browsers"] if b["name"] == "chromium"]

    if system_chromium:
        primary = system_chromium[0]
        return {
            "recommended": "system",
            "browser": primary["name"],
            "path": primary["path"],
            "version": primary["version"],
            "reason": f"System {primary['name']} found at {primary['path']} ({primary['version']}). Prefer system browser for profile persistence and login reuse."
        }
    elif pw_chromium:
        primary = pw_chromium[0]
        return {
            "recommended": "playwright-managed",
            "browser": "Chromium (Playwright)",
            "path": primary["path"],
            "version": "managed",
            "reason": f"No system Chromium/Chrome found. Playwright-managed Chromium available at {primary['path']}."
        }
    else:
        return {
            "recommended": "none",
            "browser": "none",
            "path": "",
            "version": "",
            "reason": "No Chromium-based browser found. Install system Chrome/Chromium or run 'playwright install chromium'."
        }


def run_doctor() -> Dict[str, Any]:
    """Run full environment audit."""
    report = {
        "distro": get_linux_distro(),
        "python": get_python_info(),
        "resources": get_system_resources(),
        "browsers": find_chromium(),
        "playwright": check_playwright(),
        "headed": check_headed_support(),
    }
    report["recommendation"] = get_recommendation(report["browsers"], report["playwright"])
    return report


def print_doctor(report: Dict[str, Any]) -> None:
    """Pretty print doctor report."""
    print("=" * 60)
    print("browserapi-lab — Environment Doctor")
    print("=" * 60)

    print(f"\n📋 Distro: {report['distro']['name']} ({report['distro']['version']}) [{report['distro']['id']}]")

    py = report["python"]
    print(f"\n🐍 Python: {py['version']} ({py['architecture']})")
    print(f"   Executable: {py['executable']}")
    print(f"   Platform: {py['platform']}")

    res = report["resources"]
    print(f"\n💾 RAM: {res['ram_gb']} GB")
    print(f"🖥️  CPU: {res['cpu_count']} cores — {res['cpu_model']}")

    print("\n🌐 Browsers (system):")
    if report["browsers"]:
        for b in report["browsers"]:
            print(f"   • {b['name']}: {b['path']} — {b['version']}")
    else:
        print("   (none found)")

    pw = report["playwright"]
    print(f"\n🎭 Playwright: {'installed' if pw['installed'] else 'NOT installed'}")
    if pw["installed"]:
        print(f"   Version: {pw['version']}")
        if pw["browsers"]:
            for b in pw["browsers"]:
                print(f"   • {b['name']}: {b['path']} ({b['type']})")
        else:
            print("   (no managed browsers installed)")

    h = report["headed"]
    print(f"\n🖥️  Headed support: DISPLAY={h['display']}, WAYLAND_DISPLAY={h['wayland']}")
    print(f"   Recommendation: {h['recommendation']}")

    rec = report["recommendation"]
    print(f"\n✅ RECOMMENDATION: {rec['recommended'].upper()}")
    print(f"   Browser: {rec['browser']}")
    if rec["path"]:
        print(f"   Path: {rec['path']}")
    print(f"   Reason: {rec['reason']}")

    if rec["recommended"] == "none":
        print(f"\n📦 To install: {pw['install_command']}")


if __name__ == "__main__":
    report = run_doctor()
    print_doctor(report)