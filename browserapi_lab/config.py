"""Configuração local por chat. Nunca importar cookies ou perfil pessoal."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

DEFAULT_CONFIG_DIR = Path.home() / '.config' / 'browserapi-lab'
PROVIDERS = {
    'gemini': 'https://gemini.google.com/app',
    'lmarena': 'https://lmarena.ai/',
}
BROWSERS = ('chromium', 'chrome', 'msedge', 'custom')
SELECTOR_KEYS = ('composer', 'send', 'user', 'assistant', 'root')


def safe_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', name):
        raise ValueError('Nome: use 1 a 64 letras, números, hífen ou sublinhado.')
    return name


def safe_url(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError('URL inválida.')
    parts = urlsplit(url)
    if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment or any(c.isspace() for c in url)):
        raise ValueError('Use URL http(s) sem senha, token, parâmetros ou fragmento.')
    try:
        parts.port
    except ValueError as exc:
        raise ValueError('Porta inválida.') from exc
    if parts.scheme != 'https' and parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Chats remotos exigem HTTPS; HTTP somente em localhost.')
    return url


def origin(url):
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == 'https' else 80)
    return parts.scheme, parts.hostname, port


@dataclass
class ChatConfig:
    name: str
    url: str
    browser: str = 'chromium'
    provider: str = 'custom'
    executable: str | None = None
    composer: str = ''
    send: str = ''
    user: str = ''
    assistant: str = ''
    root: str = 'body'
    timeout_ms: int = 60000
    stability_ms: int = 1200
    schema_version: int = 1
    session_mode: str = 'dedicated'
    voice: str = ''
    voice_signature: str = ''
    personal_installation: str = 'chrome'
    personal_profile: str = ''

    def validate(self):
        from .profiles import CHROME_INSTALLATIONS, profile_name
        if self.personal_installation not in CHROME_INSTALLATIONS:
            raise ValueError('Instalação pessoal inválida')
        if not isinstance(self.personal_profile,str):
            raise ValueError('Perfil inválido')
        if self.personal_profile:
            profile_name(self.personal_profile)
        safe_name(self.name)
        safe_url(self.url)
        if not isinstance(self.voice, str) or len(self.voice) > 1000:
            raise ValueError('Seletor de voz inválido.')
        if not isinstance(self.voice_signature, str) or (self.voice_signature and not re.fullmatch('[0-9a-f]{64}', self.voice_signature)):
            raise ValueError('Estado do controle de voz inválido.')
        if self.browser not in BROWSERS or self.provider not in (*PROVIDERS, 'custom', 'fixture'):
            raise ValueError('Navegador ou provedor inválido.')
        if self.session_mode not in ('dedicated', 'existing_chrome'):
            raise ValueError('Modo de sessão inválido.')
        if self.session_mode == 'existing_chrome' and self.browser != 'chrome':
            raise ValueError('Sessão existente exige Google Chrome.')
        if self.schema_version != 1 or type(self.schema_version) is not int:
            raise ValueError('Versão da configuração incompatível.')
        if self.browser == 'custom':
            if not isinstance(self.executable, str) or not Path(self.executable).is_absolute():
                raise ValueError('Informe caminho absoluto para um binário Chromium.')
        elif self.executable is not None:
            raise ValueError('Binário explícito somente no modo custom.')
        for key in SELECTOR_KEYS:
            value = getattr(self, key)
            if not isinstance(value, str) or len(value) > 1000:
                raise ValueError('Seletor inválido; execute repair.')
        if (type(self.timeout_ms) is not int or not 500 <= self.timeout_ms <= 300000
                or type(self.stability_ms) is not int or not 200 <= self.stability_ms <= 10000):
            raise ValueError('Janelas de tempo inválidas.')
        return self

    @property
    def ready(self):
        return all(getattr(self, key).strip() for key in SELECTOR_KEYS)


class ConfigStore:
    def __init__(self, root=DEFAULT_CONFIG_DIR):
        self.root = Path(root).expanduser()

    def _path(self, name):
        return self.root / (safe_name(name) + '.json')

    def save(self, config):
        config.validate()
        self.write_json(self._path(config.name), asdict(config))

    def load(self, name):
        path = self._path(name)
        if path.stat().st_size > 65536:
            raise ValueError('Configuração excede o limite.')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            config = ChatConfig(**data).validate()
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError('Configuração inválida; execute configure novamente.') from exc
        if config.name != name:
            raise ValueError('Nome interno não corresponde ao arquivo.')
        return config

    def names(self):
        if not self.root.exists():
            return []
        return sorted(p.stem for p in self.root.glob('*.json') if not p.stem.endswith('.status'))

    def delete(self, name):
        """Remove only this local connection and receipt, never Chrome/history."""
        path = self._path(name)
        if not path.exists():
            raise ValueError('Conexão não encontrada.')
        path.unlink()
        (self.root / (safe_name(name) + '.status.json')).unlink(missing_ok=True)

    def save_status(self, name, status):
        # O chamador fornece só um recibo sanitizado; nunca texto da conversa.
        self.write_json(self.root / (safe_name(name) + '.status.json'), status)

    def status(self, name):
        path = self.root / (safe_name(name) + '.status.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    @staticmethod
    def write_json(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
