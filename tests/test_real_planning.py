"""Planejamento real da troca de local, com pastas temporárias (nunca a biblioteca de verdade)."""

import shutil
import tempfile
from pathlib import Path

import pytest
from conftest import ROOT

from nuvem_ruscher.core.config import AppConfig
from nuvem_ruscher.core.migration import MIGRATION_MARKER, Mode

real = pytest.importorskip("nuvem_ruscher.backend.real")


@pytest.fixture
def tmp_path():
    # Fora de /tmp: a validação recusa /tmp como local de fotos (de propósito).
    base = ROOT / "build" / "testes"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="plan-", dir=base))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "home" / "maria" / "Fotos" / "Nuvem"
    for folder in ("library", "upload"):
        (source / folder).mkdir(parents=True)
        (source / folder / ".immich").write_text("")
    (source / "library" / "foto.jpg").write_bytes(b"x" * 2048)
    b = real.RealBackend()
    monkeypatch.setattr(b, "load_config", lambda: AppConfig(installed=True, upload_location=str(source)))
    b.source = source
    return b


def test_same_disk_prefers_rename(backend, tmp_path):
    dest = str(tmp_path / "home" / "maria" / "Fotos" / "Nuvem nova")
    plan = backend.plan_migration(dest)
    assert plan.stats.files == 3 and plan.stats.bytes == 2048
    assert plan.destination.same_fs
    assert plan.mode is Mode.RENAME
    assert plan.can_start, plan.problems


def test_missing_parent_means_disk_not_connected(backend, tmp_path):
    plan = backend.plan_migration(str(tmp_path / "home" / "maria" / "Disco sumiu" / "Nuvem"))
    assert "dest-missing" in plan.problems


def test_resumable_copy_is_recognized(backend, tmp_path):
    dest = tmp_path / "home" / "maria" / "Outra"
    dest.mkdir(parents=True)
    (dest / MIGRATION_MARKER).write_text(f"SOURCE={backend.source}\n")
    (dest / "library").mkdir()
    plan = backend.plan_migration(str(dest), Mode.COPY)
    assert plan.destination.resumable_from == str(backend.source)
    assert "dest-not-empty" not in plan.problems


def test_adopt_detects_existing_library(backend, tmp_path):
    dest = tmp_path / "home" / "maria" / "Copia"
    shutil.copytree(backend.source, dest)
    plan = backend.plan_migration(str(dest))
    assert plan.mode is Mode.ADOPT
    assert plan.destination.files == 3


def test_symlink_in_destination_path(backend, tmp_path):
    link = tmp_path / "home" / "maria" / "atalho"
    link.symlink_to(tmp_path)
    plan = backend.plan_migration(str(link / "Nuvem"))
    assert "dest-symlink" in plan.problems
