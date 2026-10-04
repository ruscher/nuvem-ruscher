"""Plano de download das imagens (como usuário) e progresso do ``compose pull``.

Veja ADR-006: o ``.env`` real é 600 (root). Para baixar com progresso e poder
cancelar, montamos uma cópia legível do projeto com um ``.env`` sem segredos.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER_PASSWORD = "somenteParaDownload0"
PUBLIC_ENV_KEYS = (
    "UPLOAD_LOCATION",
    "DB_DATA_LOCATION",
    "TZ",
    "IMMICH_VERSION",
    "DB_USERNAME",
    "DB_DATABASE_NAME",
)


def env_quote(value: str) -> str:
    if any(c in value for c in '"$`\\\n'):
        raise ValueError(f"valor impróprio para .env: {value!r}")
    return f'"{value}"'


def write_pull_plan(dest: Path, compose_text: str, override_text: str, env: dict[str, str]) -> Path:
    """Escreve a cópia do projeto usada só para ``docker compose pull``."""
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    (dest / "docker-compose.yml").write_text(compose_text, encoding="utf-8")
    (dest / "docker-compose.override.yml").write_text(override_text, encoding="utf-8")
    lines = ["# Cópia sem segredos, usada apenas para baixar as imagens."]
    for key in PUBLIC_ENV_KEYS:
        if key in env:
            lines.append(f"{key}={env_quote(env[key])}")
    lines.append(f"DB_PASSWORD={PLACEHOLDER_PASSWORD}")
    env_path = dest / ".env"
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_path, 0o600)
    return dest


def pull_args(project_dir: Path) -> list[str]:
    return ["compose", "--project-directory", str(project_dir), "--progress", "json", "pull"]


@dataclass
class _Layer:
    current: int = 0
    total: int = 0
    done: bool = False


@dataclass
class PullProgress:
    """Agrega as linhas JSON do ``docker compose --progress json pull``.

    Cada camada (``parent_id`` = serviço) informa ``current``/``total`` enquanto baixa.
    Camadas já presentes chegam como "Already exists"/"Pull complete" sem bytes.
    """

    layers: dict[str, _Layer] = field(default_factory=dict)
    services: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    _best_fraction: float = 0.0
    _samples: list[tuple[float, int]] = field(default_factory=list)

    def feed(self, line: str, now: float | None = None) -> bool:
        """Processa uma linha. Devolve True se era uma linha de progresso."""
        line = line.strip()
        if not line.startswith("{"):
            return False
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return False
        ident = str(msg.get("id") or "")
        parent = str(msg.get("parent_id") or "")
        text = str(msg.get("text") or "")
        status = str(msg.get("status") or "")
        lowered = f"{status} {text}".lower()
        if "error" in lowered:
            self.errors.append(str(msg.get("details") or text or status))
        if not parent:
            if ident:
                self.services[ident] = text or status
            return True
        layer = self.layers.setdefault(f"{parent}/{ident}", _Layer())
        total = int(msg.get("total") or 0)
        current = int(msg.get("current") or 0)
        if "download" in lowered and total:
            layer.total = max(layer.total, total)
            layer.current = max(layer.current, min(current, total))
        if any(
            word in lowered
            for word in (
                "download complete",
                "verifying checksum",
                "extracting",
                "pull complete",
                "already exists",
            )
        ):
            if layer.total:
                layer.current = layer.total
            layer.done = True
        self._samples.append((time.monotonic() if now is None else now, self.downloaded))
        self._samples = self._samples[-40:]
        return True

    @property
    def downloaded(self) -> int:
        return sum(layer.current for layer in self.layers.values())

    @property
    def total(self) -> int:
        return sum(layer.total for layer in self.layers.values())

    @property
    def fraction(self) -> float:
        """Fração monotônica (nunca volta, mesmo quando surgem camadas novas)."""
        if not self.layers:
            return self._best_fraction
        # Cada camada vale o mesmo; as que estão baixando contam pela fração já recebida.
        # (Somar bytes superestima: o tamanho de uma camada só aparece quando ela começa.)
        parts = 0.0
        for layer in self.layers.values():
            if layer.done:
                parts += 1.0
            elif layer.total:
                parts += layer.current / layer.total
        value = parts / len(self.layers)
        self._best_fraction = max(self._best_fraction, min(value, 0.999))
        return self._best_fraction

    @property
    def unpacking(self) -> bool:
        """Tudo baixado, mas o Docker ainda descompacta (0 B/s perto do fim)."""
        return bool(self.layers) and all(layer.done for layer in self.layers.values()) and self._best_fraction < 1

    def speed(self) -> float:
        """Bytes por segundo nos últimos segundos."""
        if len(self._samples) < 2:
            return 0.0
        (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
        if t1 - t0 < 0.5:
            return 0.0
        return max(0.0, (b1 - b0) / (t1 - t0))

    def finish(self) -> None:
        self._best_fraction = 1.0
