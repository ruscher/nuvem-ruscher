"""Releases do Immich no GitHub: versões estáveis, novidades e alertas."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from nuvem_ruscher.core.validation import VERSION_RE

BREAKING_HEADING = re.compile(r"^#{1,6}\s*.*(breaking|🚨)", re.IGNORECASE)
ANY_HEADING = re.compile(r"^#{1,6}\s")


@dataclass(frozen=True)
class Release:
    tag: str
    version: tuple[int, int, int]
    name: str
    body: str
    published: str  # AAAA-MM-DD
    url: str

    @property
    def has_breaking(self) -> bool:
        return bool(breaking_sections(self.body))


def version_tuple(tag: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.match(tag)
    if not match:
        return None
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def parse_releases(text: str) -> list[Release]:
    """Lista da API do GitHub → releases estáveis, da mais nova para a mais velha."""
    releases: list[Release] = []
    for item in json.loads(text):
        if item.get("draft") or item.get("prerelease"):
            continue
        tag = str(item.get("tag_name") or "")
        version = version_tuple(tag)
        if version is None:
            continue
        releases.append(
            Release(
                tag=tag,
                version=version,
                name=str(item.get("name") or tag),
                body=str(item.get("body") or ""),
                published=str(item.get("published_at") or "")[:10],
                url=str(item.get("html_url") or ""),
            )
        )
    releases.sort(key=lambda r: r.version, reverse=True)
    return releases


def breaking_sections(body: str) -> list[str]:
    """Trechos sob títulos “Breaking Changes”/🚨 (sem o título)."""
    sections: list[str] = []
    current: list[str] | None = None
    for line in body.splitlines():
        if ANY_HEADING.match(line):
            if current is not None and any(x.strip() for x in current):
                sections.append("\n".join(current).strip())
            current = [] if BREAKING_HEADING.match(line) else None
            continue
        if current is not None:
            current.append(line)
    if current is not None and any(x.strip() for x in current):
        sections.append("\n".join(current).strip())
    return sections


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: Release | None
    pending: tuple[Release, ...]  # releases entre a atual (exclusiva) e a mais nova

    @property
    def available(self) -> bool:
        return self.latest is not None and bool(self.pending)

    @property
    def major_change(self) -> bool:
        cur = version_tuple(self.current)
        return bool(self.latest and cur and self.latest.version[0] != cur[0])

    @property
    def breaking(self) -> list[tuple[str, str]]:
        """(tag, texto) de cada release pendente com mudanças incompatíveis."""
        out: list[tuple[str, str]] = []
        for release in self.pending:
            for section in breaking_sections(release.body):
                out.append((release.tag, section))
        return out


def update_info(current: str, releases: list[Release]) -> UpdateInfo:
    cur = version_tuple(current)
    if cur is None or not releases:
        return UpdateInfo(current, releases[0] if releases else None, ())
    pending = tuple(r for r in releases if r.version > cur)
    return UpdateInfo(current, releases[0], pending)


def br_date(iso: str) -> str:
    """'2026-09-28' → '28/09/2026' (mantém o texto se não for uma data)."""
    parts = iso.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return iso


def simple_markdown_to_pango(text: str, limit: int = 6000) -> str:
    """Converte o Markdown das notas para marcação Pango segura (subconjunto)."""
    from html import escape

    lines_out: list[str] = []
    for raw in text[:limit].splitlines():
        line = raw.rstrip()
        if line.startswith("<!--"):
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            lines_out.append(f"\n<b>{escape(heading.group(2))}</b>")
            continue
        bullet = re.match(r"^\s*[*-]\s+(.*)$", line)
        content = escape(bullet.group(1) if bullet else line)
        content = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", content)
        content = re.sub(r"`(.+?)`", r"<tt>\1</tt>", content)
        content = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', content)
        content = re.sub(r"(?<![\"=>])(https://github\.com/\S+/pull/(\d+))", r'<a href="\1">#\2</a>', content)
        lines_out.append(f"  •  {content}" if bullet else content)
    return "\n".join(lines_out).strip()


class ReleaseCache:
    """Cache de 1 hora em ~/.cache/nuvem-ruscher (a API do GitHub limita 60 req/h)."""

    def __init__(self, path: Path, ttl: float = 3600) -> None:
        self.path = path
        self.ttl = ttl

    def get(self) -> str | None:
        try:
            if time.time() - self.path.stat().st_mtime < self.ttl:
                return self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        return None

    def get_stale(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return None

    def put(self, text: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
