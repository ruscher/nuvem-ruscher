"""Internacionalização: o texto-fonte é inglês e todo texto visível passa pelo gettext."""

import ast
import gettext
import locale
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

from nuvem_ruscher import i18n

# Métodos e argumentos de widgets que recebem texto mostrado ao usuário.
TEXT_METHODS = {
    "set_title",
    "set_subtitle",
    "set_label",
    "set_text",
    "set_markup",
    "set_tooltip_text",
    "set_tooltip_markup",
    "set_description",
    "set_placeholder_text",
    "set_heading",
    "set_body",
    "set_button_label",
    "add_response",
    "add_titled",
    "add_titled_with_icon",
    "append_section",
}
TEXT_KWARGS = {
    "title",
    "subtitle",
    "label",
    "tooltip_text",
    "description",
    "heading",
    "body",
    "placeholder_text",
    "button_label",
}
# Nomes próprios, marcas e textos sem palavras (não se traduzem).
ALLOWED = {"Nuvem Ruscher", "Immich", "Tailscale", "Play Store", "F-Droid", "GitHub", "ruscher"}
ALLOWED.add("Novo volume")  # rótulo do disco fictício do --simulate (dado, não interface)
ALLOWED.add("nuvem-ruscher")  # nome técnico do array RAID (identificador)
WORDS = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def _visible_literals(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        candidates = []
        if name in TEXT_METHODS:
            # add_response(id, label), add_titled(child, name, title): o texto é o último argumento.
            candidates.append(node.args[-1] if node.args else None)
        candidates += [kw.value for kw in node.keywords if kw.arg in TEXT_KWARGS]
        for arg in candidates:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value.strip()
                if WORDS.search(text) and text not in ALLOWED:
                    found.append(f"{path.relative_to(ROOT)}:{arg.lineno}: {text!r}")
    return found


def test_no_hardcoded_visible_strings():
    problems = []
    for path in sorted((ROOT / "nuvem_ruscher").rglob("*.py")):
        problems += _visible_literals(path)
    assert problems == [], "texto visível fora do gettext:\n" + "\n".join(problems)


def _pot_msgids() -> list[str]:
    text = (ROOT / "po/nuvem-ruscher.pot").read_text(encoding="utf-8")
    ids = []
    for block in text.split("\n\n")[1:]:
        m = re.search(r'^msgid ((?:".*"\n)+)', block, re.MULTILINE)
        ids.append("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))))
    return ids


def test_source_language_is_english():
    """Letras típicas do português não aparecem nos textos-fonte."""
    portuguese = re.compile(r"[ãõçáéíóúâêôà]|\b(não|você|disco|pasta|servidor|senha)\b", re.IGNORECASE)
    offenders = [m for m in _pot_msgids() if portuguese.search(m)]
    assert offenders == []


@pytest.mark.skipif(not shutil.which("msgfmt"), reason="gettext ausente")
def test_portuguese_catalog_and_english_fallback(tmp_path, monkeypatch):
    mo_dir = tmp_path / "pt_BR" / "LC_MESSAGES"
    mo_dir.mkdir(parents=True)
    subprocess.run(
        ["msgfmt", "-o", str(mo_dir / "nuvem-ruscher.mo"), str(ROOT / "po/pt_BR.po")], check=True, capture_output=True
    )
    saved = locale.setlocale(locale.LC_ALL)
    try:
        for var in ("LC_ALL", "LC_MESSAGES"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LANG", "C.UTF-8")  # setlocale() não pode deixar o processo em ASCII
        monkeypatch.setenv("LANGUAGE", "pt_BR")
        i18n.setup(tmp_path)
        assert i18n._("Cancel") == "Cancelar"
        assert i18n._("Step {n} of {total}").format(n=1, total=6) == "Passo 1 de 6"
        monkeypatch.setenv("LANGUAGE", "en")
        i18n.setup(tmp_path)
        assert i18n._("Cancel") == "Cancel"
    finally:
        i18n._translation = gettext.NullTranslations()
        locale.setlocale(locale.LC_ALL, saved)
