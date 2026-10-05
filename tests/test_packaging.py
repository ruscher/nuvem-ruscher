"""Instalação: caminhos relocáveis (/usr no pacman, Nix Store), conteúdo do pacote e metadados.

O "make install" é a única receita de instalação; o PKGBUILD e o Nix só escolhem PREFIX,
DESTDIR e PYTHON. Estes testes instalam de verdade numa pasta temporária.
"""

import gettext
import os
import re
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from conftest import ROOT

import nuvem_ruscher
from nuvem_ruscher import APP_ID, paths
from nuvem_ruscher.constants import HELPER_PATH

needs_make = pytest.mark.skipif(not shutil.which("make"), reason="make ausente")
needs_msgfmt = pytest.mark.skipif(not shutil.which("msgfmt"), reason="gettext ausente")
SOURCE_FILES = ("Makefile", "LICENSE", "bin", "nuvem_ruscher", "helper", "data", "po")


def make_install(tree: Path, destdir: Path | None, prefix: Path | str, python: str) -> None:
    args = ["make", "-s", "-C", str(tree), f"PREFIX={prefix}", f"PYTHON={python}", "install"]
    if destdir is not None:
        args.insert(-1, f"DESTDIR={destdir}")
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=120)


def copy_tree(dest: Path) -> Path:
    """Cópia mínima do projeto, como a que o PKGBUILD e o Nix recebem (sem .git)."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    dest.mkdir(parents=True, exist_ok=True)
    for name in SOURCE_FILES:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=ignore)
        else:
            shutil.copy2(src, dest / name)
    return dest


def fake_install(base: Path, prefix: str) -> Path:
    app_dir = base / prefix.lstrip("/") / "share" / "nuvem-ruscher"
    (app_dir / "nuvem_ruscher").mkdir(parents=True)
    return app_dir


class TestPaths:
    def test_source_tree(self):
        assert paths.running_from_source(ROOT)
        assert paths.install_prefix(ROOT) is None
        assert paths.helper_path(ROOT) == Path(HELPER_PATH)

    def test_pacman_layout(self, tmp_path):
        app_dir = fake_install(tmp_path, "/usr")
        assert paths.install_prefix(app_dir) == tmp_path / "usr"
        assert paths.helper_path(app_dir) == tmp_path / "usr/lib/nuvem-ruscher/nuvem-ruscher-helper"
        assert paths.locale_dir(app_dir) == tmp_path / "usr/share/locale"

    def test_nix_store_layout(self, tmp_path):
        store = "/nix/store/0123456789abcdfghijklmnpqrsvwxyz-nuvem-ruscher-1.0.0"
        app_dir = fake_install(tmp_path, store)
        prefix = tmp_path / store.lstrip("/")
        assert paths.helper_path(app_dir) == prefix / "lib/nuvem-ruscher/nuvem-ruscher-helper"
        assert paths.locale_dir(app_dir) == prefix / "share/locale"

    def test_unknown_layout_falls_back_to_system_helper(self, tmp_path):
        odd = tmp_path / "solto"
        (odd / "nuvem_ruscher").mkdir(parents=True)
        assert paths.install_prefix(odd) is None
        assert paths.helper_path(odd) == Path(HELPER_PATH)


@pytest.fixture(scope="module")
def pkg(tmp_path_factory) -> Path:
    """Como o PKGBUILD: DESTDIR=$pkgdir PREFIX=/usr."""
    tree = copy_tree(tmp_path_factory.mktemp("arvore"))
    pkgdir = tmp_path_factory.mktemp("pkg")
    make_install(tree, pkgdir, "/usr", sys.executable)
    return pkgdir


@pytest.fixture(scope="module")
def prefix(tmp_path_factory) -> Path:
    """Como o Nix: PREFIX=$out, sem DESTDIR, com um catálogo de tradução de teste."""
    tree = copy_tree(tmp_path_factory.mktemp("arvore"))
    # Um idioma fictício prova o caminho .po → .mo → <prefixo>/share/locale sem depender
    # do conteúdo das traduções reais (que também são instaladas e testadas abaixo).
    po = (tree / "po" / "nuvem-ruscher.pot").read_text()
    po = po.replace(
        'msgid "Instala e cuida do Immich no BigLinux."\nmsgstr ""',
        'msgid "Instala e cuida do Immich no BigLinux."\nmsgstr "Tradução de teste."',
    )
    (tree / "po" / "xx.po").write_text(po)
    prefix = tmp_path_factory.mktemp("loja") / "0123-nuvem-ruscher"
    make_install(tree, None, prefix, sys.executable)
    # Versão marcada: prova que foi esta cópia, e não a do repositório, que rodou.
    init = prefix / "share/nuvem-ruscher/nuvem_ruscher/__init__.py"
    init.write_text(init.read_text().replace(f'VERSION = "{nuvem_ruscher.VERSION}"', 'VERSION = "9.9.9-teste"'))
    return prefix


@needs_make
class TestMakeInstall:
    def test_everything_under_usr(self, pkg):
        """O pacote não tem nada em /etc nem /var: o pacman nunca toca na configuração do servidor."""
        assert sorted(p.name for p in pkg.iterdir()) == ["usr"]
        tops = {p.relative_to(pkg / "usr").parts[0] for p in pkg.rglob("*") if p.is_file()}
        assert tops == {"bin", "lib", "share"}

    def test_expected_files(self, pkg):
        usr = pkg / "usr"
        for rel in (
            "bin/nuvem-ruscher",
            "lib/nuvem-ruscher/nuvem-ruscher-helper",
            "share/nuvem-ruscher/nuvem_ruscher/main.py",
            "share/nuvem-ruscher/nuvem_ruscher/ui/style.css",
            "share/nuvem-ruscher/data/illustrations/nuvem-ruscher-welcome.svg",
            "share/nuvem-ruscher/data/icons/hicolor/symbolic/apps/nr-status-ok-symbolic.svg",
            f"share/applications/{APP_ID}.desktop",
            f"share/metainfo/{APP_ID}.metainfo.xml",
            f"share/polkit-1/actions/{APP_ID}.policy",
            f"share/icons/hicolor/scalable/apps/{APP_ID}.svg",
            f"share/icons/hicolor/symbolic/apps/{APP_ID}-symbolic.svg",
            "share/licenses/nuvem-ruscher/LICENSE",
        ):
            assert (usr / rel).is_file(), rel
        assert (usr / "bin/nuvem-ruscher").stat().st_mode & 0o777 == 0o755
        assert (usr / "lib/nuvem-ruscher/nuvem-ruscher-helper").stat().st_mode & 0o777 == 0o755
        assert list((usr / "share/nuvem-ruscher/nuvem_ruscher").glob("__pycache__/*.pyc"))

    def test_no_development_files(self, pkg):
        names = {p.name for p in pkg.rglob("*")}
        for unwanted in ("tests", "docs", "screenshots", "pyproject.toml", "Makefile", ".git", "tour.py"):
            assert unwanted not in names

    def test_launcher_pins_python(self, pkg):
        """Sem "env python3": um python3 do conda/pyenv no PATH não pode abrir o app."""
        assert (pkg / "usr/bin/nuvem-ruscher").read_text().splitlines()[0] == f"#!{sys.executable}"

    def test_policy_points_to_installed_helper(self, pkg):
        text = (pkg / f"usr/share/polkit-1/actions/{APP_ID}.policy").read_text()
        assert "@HELPER_PATH@" not in text
        tree = ET.fromstring(text)
        exec_paths = {a.text for a in tree.iter("annotate") if a.get("key") == "org.freedesktop.policykit.exec.path"}
        assert exec_paths == {HELPER_PATH}

    def test_uninstall_removes_only_installed_files(self, tmp_path):
        tree = copy_tree(tmp_path / "arvore")
        destdir = tmp_path / "raiz"
        make_install(tree, destdir, "/usr", sys.executable)
        keep = destdir / "usr/share/nuvem-ruscher/meu-arquivo"
        keep.write_text("não é do pacote")
        subprocess.run(
            ["make", "-s", "-C", str(tree), f"DESTDIR={destdir}", "PREFIX=/usr", "uninstall"],
            check=True,
            capture_output=True,
        )
        left = sorted(str(p.relative_to(destdir)) for p in destdir.rglob("*") if p.is_file())
        assert left == ["usr/share/nuvem-ruscher/meu-arquivo"]


@needs_make
@needs_msgfmt
class TestRelocatedPrefix:
    """Instalado fora de /usr (como no Nix Store), o app usa só a própria cópia."""

    def run(self, prefix: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
        clean = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": str(prefix), "LANG": "C.UTF-8", **env}
        return subprocess.run(
            [sys.executable, str(prefix / "bin/nuvem-ruscher"), *args],
            capture_output=True,
            text=True,
            env=clean,
            cwd=prefix,
            timeout=60,
            check=False,
        )

    def test_launcher_loads_own_copy(self, prefix):
        proc = self.run(prefix, "--version")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "Nuvem Ruscher 9.9.9-teste"

    def test_translation_from_prefix(self, prefix):
        assert (prefix / "share/locale/xx/LC_MESSAGES/nuvem-ruscher.mo").is_file()
        assert "Tradução de teste." in self.run(prefix, "--help", LANGUAGE="xx").stdout
        # Texto-fonte em pt-BR: sem catálogo, e é para onde qualquer idioma sem tradução cai.
        assert "Instala e cuida do Immich" in self.run(prefix, "--help", LANGUAGE="pt_BR").stdout
        assert "Instala e cuida do Immich" in self.run(prefix, "--help", LANGUAGE="de").stdout

    def test_real_catalogs_installed(self, prefix):
        for po in sorted((ROOT / "po").glob("*.po")):
            assert (prefix / f"share/locale/{po.stem}/LC_MESSAGES/nuvem-ruscher.mo").is_file(), po.name
        if (ROOT / "po/en.po").exists():
            assert "Installs and looks after Immich" in self.run(prefix, "--help", LANGUAGE="en_US").stdout

    def test_helper_and_policy_follow_prefix(self, prefix):
        helper = prefix / "lib/nuvem-ruscher/nuvem-ruscher-helper"
        code = "from nuvem_ruscher import paths; print(paths.helper_path()); print(paths.locale_dir())"
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env={"PYTHONPATH": str(prefix / "share/nuvem-ruscher")},
            cwd=prefix,
            capture_output=True,
            text=True,
            check=True,
        )
        assert proc.stdout.splitlines() == [str(helper), str(prefix / "share/locale")]
        policy = (prefix / f"share/polkit-1/actions/{APP_ID}.policy").read_text()
        assert f">{helper}</annotate>" in policy


@needs_msgfmt
@pytest.mark.parametrize("po", sorted((ROOT / "po").glob("*.po")), ids=lambda p: p.stem)
def test_catalog_complete_and_consistent(po, tmp_path):
    """Toda mensagem traduzida, sem "fuzzy", com os mesmos {marcadores}, quebras e <b>."""
    mo = tmp_path / "nuvem-ruscher.mo"
    subprocess.run(["msgfmt", "--check", "-o", str(mo), str(po)], check=True, capture_output=True)
    assert "#, fuzzy" not in po.read_text().split("\n\n", 1)[1]
    with mo.open("rb") as fp:
        catalog = gettext.GNUTranslations(fp)._catalog
    pot = (ROOT / "po/nuvem-ruscher.pot").read_text()
    msgids = {k for k in catalog if k}
    assert len(msgids) == pot.count("\nmsgid ") - 1, "há mensagens sem tradução"
    for msgid in msgids:
        msgstr = catalog[msgid]
        assert sorted(re.findall(r"\{\w+\}", msgid)) == sorted(re.findall(r"\{\w+\}", msgstr)), msgid
        for token in ("\n", "<b>", "</b>"):
            assert msgid.count(token) == msgstr.count(token), msgid
        assert msgid.startswith(" ") == msgstr.startswith(" "), msgid


class TestMetadata:
    def test_versions_match(self):
        version = nuvem_ruscher.VERSION
        assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"] == version
        helper = (ROOT / "helper/nuvem-ruscher-helper").read_text()
        assert f'readonly HELPER_VERSION="{version}"' in helper
        metainfo = ET.parse(ROOT / f"data/{APP_ID}.metainfo.xml").getroot()
        assert metainfo.find("releases/release").get("version") == version
        pkgbuild = ROOT / "packaging/PKGBUILD"
        if pkgbuild.exists():  # fora da cópia que o Nix recebe
            assert re.search(rf"^pkgver={re.escape(version)}$", pkgbuild.read_text(), re.MULTILINE)

    def test_ids_match(self):
        desktop = (ROOT / f"data/{APP_ID}.desktop").read_text()
        assert "\nIcon=io.github.ruscher.NuvemRuscher\n" in desktop
        assert "\nExec=nuvem-ruscher\n" in desktop
        assert f"\nStartupWMClass={APP_ID}\n" in desktop
        metainfo = ET.parse(ROOT / f"data/{APP_ID}.metainfo.xml").getroot()
        assert metainfo.findtext("id") == APP_ID
        assert metainfo.findtext("launchable") == f"{APP_ID}.desktop"
        assert metainfo.findtext("project_license") == "GPL-3.0-or-later"
        policy = ET.fromstring((ROOT / f"data/{APP_ID}.policy.in").read_text())
        assert {a.get("id") for a in policy.iter("action")} == {
            f"{APP_ID}.{name}" for name in ("manage", "start", "stop", "restart")
        }
        assert policy.findtext("icon_name") == APP_ID
