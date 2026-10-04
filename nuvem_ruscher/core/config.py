"""Configuração pública (/etc/nuvem-ruscher) e estado do usuário (~/.config)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nuvem_ruscher.constants import CONF_FILE


@dataclass
class AppConfig:
    """Conteúdo de /etc/nuvem-ruscher/nuvem-ruscher.conf (escrito pelo helper)."""

    installed: bool = False
    immich_version: str = ""
    upload_location: str = ""
    mount_point: str = ""
    mount_unit: str = ""
    fs_type: str = ""
    transcode: str = "cpu"
    ml: str = "cpu"
    timezone: str = ""
    db_data_location: str = ""
    raw: dict[str, str] = field(default_factory=dict)


def parse_conf(text: str) -> AppConfig:
    """Lê ``CHAVE=valor`` linha a linha. Valores são crus (podem ter espaço)."""
    raw: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip()] = value
    return AppConfig(
        installed=raw.get("INSTALLED") == "1",
        immich_version=raw.get("IMMICH_VERSION", ""),
        upload_location=raw.get("UPLOAD_LOCATION", ""),
        mount_point=raw.get("MOUNT_POINT", ""),
        mount_unit=raw.get("MOUNT_UNIT", ""),
        fs_type=raw.get("FS_TYPE", ""),
        transcode=raw.get("TRANSCODE", "cpu"),
        ml=raw.get("ML", "cpu"),
        timezone=raw.get("TZ", ""),
        db_data_location=raw.get("DB_DATA_LOCATION", ""),
        raw=raw,
    )


def load_conf(path: str = CONF_FILE) -> AppConfig:
    try:
        return parse_conf(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return AppConfig()


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "nuvem-ruscher"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "nuvem-ruscher"


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class UserState:
    """Progresso do assistente e preferências, em JSON (600)."""

    def __init__(self, path: Path | None = None, persistent: bool = True) -> None:
        self.path = path or config_dir() / "state.json"
        self.persistent = persistent
        self.data: dict[str, Any] = {}
        if persistent:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = loaded
            except (OSError, ValueError):
                self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        if self.persistent:
            try:
                _write_private(self.path, json.dumps(self.data, indent=2, ensure_ascii=False))
            except OSError:
                pass


class ApiKeyStore:
    """Chave de API só de estatísticas (ADR-010)."""

    def __init__(self, path: Path | None = None, persistent: bool = True) -> None:
        self.path = path or config_dir() / "api-key"
        self.persistent = persistent
        self._memory: str | None = None

    def load(self) -> str | None:
        if not self.persistent:
            return self._memory
        try:
            key = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return key or None

    def save(self, key: str) -> None:
        if not self.persistent:
            self._memory = key
            return
        _write_private(self.path, key + "\n")

    def clear(self) -> None:
        self._memory = None
        if self.persistent:
            try:
                self.path.unlink()
            except OSError:
                pass
