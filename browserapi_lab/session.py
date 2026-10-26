"""Sessão persistente, lock de perfil e sanitização (Marco 2).

Regras do briefing implementadas aqui:

* perfil **exclusivo** do projeto (nunca o perfil pessoal do Chrome);
* nunca abrir o mesmo ``user_data_dir`` em dois processos — lock cooperativo com
  ``fcntl.flock`` e falha rápida com erro claro;
* nunca registrar cookies, tokens ou conteúdo privado — :func:`sanitize_storage_state`
  devolve apenas estrutura (origens, nomes de chaves, contagens).

Somente biblioteca padrão. Playwright é importado tardiamente por quem chama.
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:  # pragma: no cover - Linux é o alvo; em outro SO o lock vira erro explícito
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

PROFILES_ROOT = Path("profiles")


class ProfileBusyError(RuntimeError):
    """Perfil já está em uso por outro processo do laboratório."""


@dataclass
class ProfileLock:
    """Lock cooperativo de um diretório de perfil.

    Não protege contra processos alheios ao laboratório (limitação documentada),
    apenas contra duas execuções do próprio laboratório — que é a causa real de
    corrupção de perfil no uso pessoal.
    """

    profile_dir: Path
    handle: Optional[int] = None

    @property
    def lock_path(self) -> Path:
        return Path(self.profile_dir) / ".browserapi-lab.lock"

    def acquire(self) -> "ProfileLock":
        if fcntl is None:  # pragma: no cover
            raise RuntimeError("lock de perfil requer fcntl (Linux/Unix)")
        path = Path(self.profile_dir)
        path.mkdir(parents=True, exist_ok=True)
        self.handle = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.handle)
            self.handle = None
            info = read_lock_info(self.lock_path)
            raise ProfileBusyError(
                "perfil em uso: {dir} (pid={pid}, host={host}, desde={since}). "
                "Feche a outra execução do laboratório antes de abrir este perfil.".format(
                    dir=path,
                    pid=info.get("pid"),
                    host=info.get("host"),
                    since=info.get("started_utc"),
                )
            ) from exc
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "schema_version": "1.0",
        }
        os.ftruncate(self.handle, 0)
        os.write(self.handle, json.dumps(payload).encode("utf-8"))
        os.fsync(self.handle)
        return self

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self.handle, fcntl.LOCK_UN)
            os.close(self.handle)
        finally:
            self.handle = None

    def __enter__(self) -> "ProfileLock":
        return self.acquire()

    def __exit__(self, *exc_info: Any) -> None:
        self.release()


def read_lock_info(lock_path: Path) -> Dict[str, Any]:
    try:
        with open(lock_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def profile_path(name: str = "default", root: Path | str = PROFILES_ROOT) -> Path:
    """Diretório de perfil exclusivo do projeto.

    Nomes são sanitizados: nunca saem de ``root`` e nunca apontam para o perfil
    pessoal do usuário (``~/.config/chromium``, ``~/.config/google-chrome`` etc.).
    """
    safe = "".join(ch for ch in str(name) if ch.isalnum() or ch in "-_.")
    safe = safe.strip(".") or "default"
    if safe in (".", "..") or "/" in safe:
        raise ValueError(f"nome de perfil inválido: {name!r}")
    return Path(root) / safe


def ensure_profile(name: str = "default", root: Path | str = PROFILES_ROOT) -> Path:
    path = profile_path(name, root)
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------
# Sanitização (ADR-009)
# --------------------------------------------------------------------------

_SENSITIVE_KEY_HINTS = (
    "token",
    "senha",
    "credencial",
    "chave",
    "auth",
    "session",
    "cookie",
    "password",
    "passwd",
    "secret",
    "bearer",
    "jwt",
    "apikey",
    "api_key",
    "credential",
)


def is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(hint in lowered for hint in _SENSITIVE_KEY_HINTS)


def sanitize_storage_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Remove **valores** de um estado exportado pelo navegador.

    Mantém apenas o que é útil para diagnóstico: origens, nomes de chaves,
    contagens e sinalização de chaves sensíveis (sem o valor).
    """
    cookies = state.get("cookies") or []
    origins = state.get("origins") or []

    cookie_summary: Dict[str, Any] = {}
    for cookie in cookies:
        domain = str(cookie.get("domain") or "?")
        entry = cookie_summary.setdefault(domain, {"count": 0, "sensitive_names": []})
        entry["count"] += 1
        name = str(cookie.get("name") or "")
        if is_sensitive_key(name) and name not in entry["sensitive_names"]:
            entry["sensitive_names"].append(name)

    origin_summary = []
    for origin in origins:
        local = origin.get("localStorage") or []
        indexed_db = origin.get("indexedDB") or []
        origin_summary.append(
            {
                "origin": origin.get("origin"),
                "local_storage_keys": sorted(
                    {str(item.get("name")) for item in local if item.get("name")}
                ),
                "local_storage_sensitive": sorted(
                    {
                        str(item.get("name"))
                        for item in local
                        if is_sensitive_key(str(item.get("name")))
                    }
                ),
                "indexed_db_databases": sorted(
                    {str(db.get("name")) for db in indexed_db if db.get("name")}
                ),
                "local_storage_count": len(local),
            }
        )

    return {
        "schema_version": "1.0",
        "cookie_domains": cookie_summary,
        "cookie_count": len(cookies),
        "origins": origin_summary,
        "has_credentials": "credentials" in state,
        "opfs_present": bool(state.get("origins") and any("opfs" in o for o in state.get("origins", []))),
    }


# sufixos de campos de diagnóstico: contagens e sinalizadores, não segredos
_SAFE_SUFFIXES = ("_count", "_len", "_size", "_present", "_keys", "_names", "_domains")


def assert_no_private_values(payload: Any, path: str = "$") -> None:
    """Falha se encontrar chave sensível carregando um **valor** (defesa em profundidade).

    Contagens e sinalizadores (``*_count``, ``*_keys``...) são permitidos: são
    exatamente o tipo de diagnóstico que queremos manter.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            sensivel = any(hint in lowered for hint in _SENSITIVE_KEY_HINTS) and not lowered.endswith(
                _SAFE_SUFFIXES
            )
            if sensivel and isinstance(value, str) and value.strip():
                raise ValueError(f"valor potencialmente privado em {path}.{key}")
            assert_no_private_values(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            assert_no_private_values(item, f"{path}[{i}]")


def supports_indexeddb_export() -> bool:
    """Consulta a API instalada em vez de assumir (briefing pede verificar)."""
    try:
        import inspect

        from playwright.sync_api import BrowserContext  # import tardio

        return "indexed_db" in inspect.signature(BrowserContext.storage_state).parameters
    except Exception:
        return False


def export_state(context: Any, path: Optional[Path] = None, indexed_db: bool = True) -> Dict[str, Any]:
    """Exporta o estado bruto (para o perfil, **nunca** versionado) e devolve o resumo.

    O arquivo bruto vai para ``profiles/<nome>/state.json`` — diretório ignorado
    pelo Git. Só o resumo sanitizado é seguro para resultados/relatórios.
    """
    if not supports_indexeddb_export():
        raw = context.storage_state(path=str(path) if path else None)
    else:
        raw = context.storage_state(
            path=str(path) if path else None,
            indexed_db=indexed_db,
        )
    return sanitize_storage_state(raw)


# --------------------------------------------------------------------------
# Marcador de persistência (usado nos experimentos de sessão)
# --------------------------------------------------------------------------

MARKER_KEY = "browserapi-lab.marker"


def set_marker(page: Any, value: Optional[str] = None) -> str:
    """Grava um marcador no localStorage da página atual."""
    marker = value or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    page.evaluate(
        "([key, value]) => window.localStorage.setItem(key, value)",
        [MARKER_KEY, marker],
    )
    return marker


def read_marker(page: Any) -> Optional[str]:
    return page.evaluate("(key) => window.localStorage.getItem(key)", MARKER_KEY)


def set_marker_indexeddb(page: Any, value: Optional[str] = None) -> str:
    """Grava o mesmo marcador no IndexedDB (quando suportado)."""
    marker = value or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    page.evaluate(
        """async ([dbName, value]) => {
      if (!('indexedDB' in window)) return 'no-indexeddb';
      await new Promise((resolve, reject) => {
        const req = indexedDB.open(dbName, 1);
        req.onupgradeneeded = () => req.result.createObjectStore('kv');
        req.onsuccess = () => {
          const db = req.result;
          const tx = db.transaction('kv', 'readwrite');
          tx.objectStore('kv').put(value, 'marker');
          tx.oncomplete = () => { db.close(); resolve(); };
          tx.onerror = () => reject(tx.error);
        };
        req.onerror = () => reject(req.error);
      });
      return 'ok';
    }""",
        ["browserapi-lab", marker],
    )
    return marker


def read_marker_indexeddb(page: Any) -> Optional[str]:
    return page.evaluate(
        """async (dbName) => {
      if (!('indexedDB' in window)) return null;
      return await new Promise((resolve) => {
        const req = indexedDB.open(dbName, 1);
        req.onupgradeneeded = () => { if (!req.result.objectStoreNames.contains('kv')) req.result.createObjectStore('kv'); };
        req.onsuccess = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains('kv')) { db.close(); return resolve(null); }
          const tx = db.transaction('kv', 'readonly');
          const get = tx.objectStore('kv').get('marker');
          get.onsuccess = () => { const v = get.result || null; db.close(); resolve(v); };
          get.onerror = () => { db.close(); resolve(null); };
        };
        req.onerror = () => resolve(null);
      });
    }""",
        "browserapi-lab",
    )
