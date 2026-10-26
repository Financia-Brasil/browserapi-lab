"""Auditoria de ambiente (Marco 0).

Responde: "este computador pode rodar o laboratorio?". Nao instala nada — apenas
diagnostica e **sugere** comandos (o briefing proibe executar ``sudo`` automaticamente).

Uso::

    python -m browserapi_lab.cli doctor
    python -m browserapi_lab.cli doctor --json results/doctor.json
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Bibliotecas de runtime exigidas por um Chromium/Chrome moderno.
# Ausencia de qualquer uma delas => navegador nao abre.
CHROMIUM_LIBS = (
    "libnss3.so",
    "libnspr4.so",
    "libatk-1.0.so.0",
    "libatk-bridge-2.0.so.0",
    "libatspi.so.0",
    "libcups.so.2",
    "libdrm.so.2",
    "libgbm.so.1",
    "libxkbcommon.so.0",
    "libX11.so.6",
    "libXcomposite.so.1",
    "libXdamage.so.1",
    "libXext.so.6",
    "libXfixes.so.3",
    "libXrandr.so.2",
    "libxcb.so.1",
    "libpango-1.0.so.0",
    "libcairo.so.2",
    "libasound.so.2",
    "libdbus-1.so.3",
    "libexpat.so.1",
    "libglib-2.0.so.0",
    "libgio-2.0.so.0",
    "libharfbuzz.so.0",
    "libfontconfig.so.1",
    "libepoxy.so.0",
)

# Bibliotecas sem as quais o Chromium ainda pode subir em headless (aviso, nao bloqueio).
CHROMIUM_OPTIONAL_LIBS = (
    "libgtk-3.so.0",
    "libwayland-client.so.0",
    "libgdk_pixbuf-2.0.so.0",
)

BROWSER_CANDIDATES = (
    ("google-chrome", "google-chrome"),
    ("google-chrome-stable", "google-chrome-stable"),
    ("chromium", "chromium"),
    ("chromium-browser", "chromium-browser"),
    ("chrome", "chrome"),
    ("microsoft-edge", "microsoft-edge"),
    ("firefox", "firefox"),
)

STATIC_BROWSER_PATHS = (
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    "/usr/bin/firefox",
)

LIB_SEARCH_DIRS = (
    "/usr/lib/x86_64-linux-gnu",
    "/usr/lib64",
    "/usr/lib",
    "/lib/x86_64-linux-gnu",
    "/lib64",
    "/lib",
)


@dataclass
class LibraryStatus:
    name: str
    found: bool
    path: Optional[str] = None


@dataclass
class BrowserInfo:
    name: str
    path: Optional[str]
    version: Optional[str]
    source: str  # "PATH" | "path" | "playwright-cache"


@dataclass
class EnvReport:
    """Relatorio completo da auditoria."""

    generated_at_utc: str = ""
    environment_kind: str = "unknown"  # local-linux | codespaces | ci | unknown
    os_name: str = ""
    os_version: str = ""
    kernel: str = ""
    arch: str = ""
    python_version: str = ""
    python_executable: str = ""
    cpu_count: Optional[int] = None
    cpu_model: str = ""
    ram_total_mb: Optional[int] = None
    disk_free_gb: Optional[float] = None
    playwright_installed: bool = False
    playwright_version: Optional[str] = None
    playwright_browsers: List[str] = field(default_factory=list)
    system_browsers: List[BrowserInfo] = field(default_factory=list)
    missing_required_libs: List[str] = field(default_factory=list)
    present_required_libs: List[str] = field(default_factory=list)
    missing_optional_libs: List[str] = field(default_factory=list)
    browser_ready: bool = False
    can_headed: bool = False
    display_server: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["system_browsers"] = [asdict(b) for b in self.system_browsers]
        return data


def detect_environment_kind() -> str:
    if os.environ.get("CODESPACES") or os.environ.get("GITHUB_CODESPACES_TOKEN"):
        return "codespaces"
    if os.environ.get("GITHUB_ACTIONS"):
        return "ci"
    if os.environ.get("CI"):
        return "ci"
    if sys.platform.startswith("linux"):
        return "local-linux"
    return "unknown"


def find_library(name: str) -> LibraryStatus:
    """Procura uma biblioteca compartilhada.

    Usa varredura direta nos diretorios padrao, alem do cache do ``ldconfig`` — em
    containers minimos o cache pode estar vazio mesmo com as bibliotecas presentes.
    """
    try:
        import ctypes.util

        found = ctypes.util.find_library(name)
        if found:
            return LibraryStatus(name=name, found=True, path=found)
    except Exception:  # pragma: no cover - defensivo
        pass

    for directory in LIB_SEARCH_DIRS:
        matches = sorted(glob.glob(os.path.join(directory, name + "*")))
        if matches:
            return LibraryStatus(name=name, found=True, path=matches[0])
    return LibraryStatus(name=name, found=False)


def check_libraries(names=CHROMIUM_LIBS) -> List[LibraryStatus]:
    return [find_library(name) for name in names]


def _run_version(command: List[str]) -> Optional[str]:
    try:
        out = subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False
        ).stdout
        return out.strip().splitlines()[0] if out.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def find_system_browsers() -> List[BrowserInfo]:
    found: List[BrowserInfo] = []
    for name, binary in BROWSER_CANDIDATES:
        path = shutil.which(binary)
        if path:
            found.append(
                BrowserInfo(name=name, path=path, version=_run_version([path, "--version"]), source="PATH")
            )
    for path in STATIC_BROWSER_PATHS:
        if os.path.exists(path) and all(b.path != path for b in found):
            found.append(
                BrowserInfo(
                    name=os.path.basename(path),
                    path=path,
                    version=_run_version([path, "--version"]),
                    source="path",
                )
            )
    return found


def find_playwright_browsers() -> List[str]:
    """Navegadores ja baixados pelo Playwright (cache padrao ou PLAYWRIGHT_BROWSERS_PATH)."""
    cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(
        os.path.expanduser("~"), ".cache", "ms-playwright"
    )
    if not os.path.isdir(cache):
        return []
    return sorted(
        name
        for name in os.listdir(cache)
        if os.path.isdir(os.path.join(cache, name))
    )


def playwright_info() -> tuple[bool, Optional[str]]:
    try:
        from importlib.metadata import version

        return True, version("playwright")
    except Exception:
        pass
    try:
        import playwright  # noqa: F401

        return True, getattr(playwright, "__version__", None)
    except Exception:
        return False, None


def read_mem_total_mb() -> Optional[int]:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def read_cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def read_os_release() -> tuple[str, str]:
    name, version = platform.system(), platform.release()
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as handle:
            data = dict(
                line.strip().split("=", 1)
                for line in handle
                if "=" in line and not line.startswith("#")
            )
        name = data.get("NAME", name).strip('"')
        version = data.get("VERSION", version).strip('"')
    except OSError:
        pass
    return name, version


def build_report(results_path: str = "results") -> EnvReport:
    import time

    os_name, os_version = read_os_release()
    pw_installed, pw_version = playwright_info()
    required = check_libraries(CHROMIUM_LIBS)
    optional = check_libraries(CHROMIUM_OPTIONAL_LIBS)
    system_browsers = find_system_browsers()
    pw_browsers = find_playwright_browsers()
    display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")

    report = EnvReport(
        generated_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        environment_kind=detect_environment_kind(),
        os_name=os_name,
        os_version=os_version,
        kernel=platform.release(),
        arch=platform.machine(),
        python_version=platform.python_version(),
        python_executable=sys.executable,
        cpu_count=os.cpu_count(),
        cpu_model=read_cpu_model(),
        ram_total_mb=read_mem_total_mb(),
        disk_free_gb=disk_free_gb(results_path),
        playwright_installed=pw_installed,
        playwright_version=pw_version,
        playwright_browsers=pw_browsers,
        system_browsers=system_browsers,
        missing_required_libs=[lib.name for lib in required if not lib.found],
        present_required_libs=[lib.name for lib in required if lib.found],
        missing_optional_libs=[lib.name for lib in optional if not lib.found],
        display_server=display,
    )

    has_browser_binary = bool(system_browsers) or bool(pw_browsers)
    report.browser_ready = (
        pw_installed and has_browser_binary and not report.missing_required_libs
    )
    report.can_headed = report.browser_ready and bool(display)

    report.notes = _notes(report, has_browser_binary)
    report.recommendations = _recommendations(report, has_browser_binary)
    return report


def _notes(report: EnvReport, has_browser_binary: bool) -> List[str]:
    notes: List[str] = []
    if report.ram_total_mb is not None and report.ram_total_mb < 6000:
        notes.append(
            f"RAM de {report.ram_total_mb} MB: manter concorrencia 1 e aba unica (briefing)."
        )
    if not report.playwright_installed:
        notes.append("playwright nao importavel neste interpretador.")
    if report.playwright_installed and not has_browser_binary:
        notes.append(
            "playwright instalado, mas nenhum navegador baixado (cache vazio ou ausente)."
        )
    if report.missing_required_libs:
        notes.append(
            "faltam %d bibliotecas obrigatorias do Chromium: %s"
            % (len(report.missing_required_libs), ", ".join(report.missing_required_libs))
        )
    if report.environment_kind in ("codespaces", "ci"):
        notes.append(
            "ambiente remoto: login e testes headed reais devem ocorrer no laptop do usuario."
        )
    if not report.can_headed and report.browser_ready:
        notes.append("sem DISPLAY/WAYLAND_DISPLAY: apenas headless e possivel aqui.")
    return notes


def _recommendations(report: EnvReport, has_browser_binary: bool) -> List[str]:
    """Sugestoes de instalacao. Nada e executado automaticamente."""
    recs: List[str] = []
    if not report.playwright_installed:
        recs.append("python3 -m pip install playwright")
    if report.playwright_installed and not has_browser_binary:
        recs.append("python3 -m playwright install chromium")
    if report.missing_required_libs:
        recs.append(
            "# dependencias do Chromium (executar manualmente, requer sudo):\n"
            "  sudo python3 -m playwright install-deps chromium\n"
            "# ou, em Debian/Ubuntu:\n"
            "  sudo apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \\\n"
            "    libatspi2.0-0 libcups2 libdrm2 libgbm1 libxkbcommon0 libxcomposite1 \\\n"
            "    libxdamage1 libxrandr2 libxfixes3 libpango-1.0-0 libcairo2 libasound2 \\\n"
            "    libdbus-1-3 libharfbuzz0b libepoxy0"
        )
    if report.browser_ready and report.environment_kind == "local-linux":
        recs.append("ambiente apto: executar 'python -m browserapi_lab.cli verify --headed'")
    return recs


def disk_free_gb(path: str = "results") -> Optional[float]:
    try:
        usage = shutil.disk_usage(os.path.abspath(path))
        return round(usage.free / (1024**3), 1)
    except OSError:
        return None


def render_text(report: EnvReport) -> str:
    lines = [
        "browserapi-lab :: doctor (Marco 0)",
        "=" * 62,
        f"ambiente ......... {report.environment_kind}",
        f"so ............... {report.os_name} {report.os_version}",
        f"kernel ........... {report.kernel} ({report.arch})",
        f"python ........... {report.python_version} ({report.python_executable})",
        f"cpu .............. {report.cpu_count} x {report.cpu_model or 'desconhecido'}",
        f"ram .............. {report.ram_total_mb} MB" if report.ram_total_mb else "ram .............. ?",
        f"disco livre ...... {report.disk_free_gb} GB" if report.disk_free_gb else "disco livre ...... ?",
        f"display .......... {report.display_server or 'nenhum'}",
        "-" * 62,
        f"playwright ....... {report.playwright_version or 'nao instalado'}",
        "navegadores pw ... " + (", ".join(report.playwright_browsers) or "nenhum"),
        "navegadores sys .. "
        + (
            ", ".join(f"{b.name}={b.version or '?'}" for b in report.system_browsers)
            or "nenhum"
        ),
        f"libs chromium .... {len(report.present_required_libs)}/{len(report.present_required_libs) + len(report.missing_required_libs)} presentes",
    ]
    if report.missing_required_libs:
        lines.append("  faltando: " + ", ".join(report.missing_required_libs))
    if report.missing_optional_libs:
        lines.append("  opcionais faltando: " + ", ".join(report.missing_optional_libs))
    lines += [
        "-" * 62,
        f"pode rodar navegador ... {'SIM' if report.browser_ready else 'NAO'}",
        f"pode rodar headed ...... {'SIM' if report.can_headed else 'NAO'}",
    ]
    if report.notes:
        lines.append("-" * 62)
        lines.append("observacoes:")
        lines += [f"  - {note}" for note in report.notes]
    if report.recommendations:
        lines.append("-" * 62)
        lines.append("sugestoes (NAO executadas automaticamente):")
        lines += [f"  {rec}" for rec in report.recommendations]
    lines.append("=" * 62)
    return "\n".join(lines)
