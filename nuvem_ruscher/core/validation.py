"""Validações compartilhadas. As mesmas regras existem no helper (Bash).

Qualquer mudança aqui precisa ser espelhada em ``helper/nuvem-ruscher-helper``
(funções ``validate_*``); os testes conferem as duas implementações.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from nuvem_ruscher.i18n import _

# Caracteres que quebrariam .env, systemd (%), shell ou o próprio fstab.
FORBIDDEN_PATH_CHARS = frozenset('"$`\\%')

# Áreas do sistema onde as fotos nunca devem ficar.
FORBIDDEN_PREFIXES = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/proc",
    "/root",
    "/sbin",
    "/sys",
    "/tmp",
    "/usr",
    "/var/lib/docker",
    "/var/lib/nuvem-ruscher",
    "/var/tmp",
)

VERSION_RE = re.compile(r"^v(\d{1,3})\.(\d{1,3})\.(\d{1,4})$")
UUID_RE = re.compile(r"^[A-Za-z0-9-]{4,36}$")
TIMEZONE_RE = re.compile(r"^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$")
# Mesmo espírito do padrão do Immich (SignUpDto), simplificado.
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$")


class ValidationError(ValueError):
    """Erro de validação com mensagem pronta para o usuário."""


def normalize_path(path: str) -> str:
    """Remove barras finais repetidas, mantendo "/" como está."""
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path


def validate_photo_path(path: str) -> str:
    """Valida a pasta das fotos e devolve a forma normalizada.

    Levanta ``ValidationError`` com uma explicação humana.
    """
    if not path:
        raise ValidationError(_("Escolha uma pasta para as fotos."))
    path = normalize_path(path)
    if not path.startswith("/"):
        raise ValidationError(_("O caminho da pasta precisa começar com “/”."))
    if len(path) > 1024:
        raise ValidationError(_("O caminho da pasta é longo demais."))
    if any(unicodedata.category(c) == "Cc" for c in path):
        raise ValidationError(_("O nome da pasta tem caracteres invisíveis não suportados."))
    bad = sorted(FORBIDDEN_PATH_CHARS.intersection(path))
    if bad:
        raise ValidationError(
            _("O nome da pasta não pode conter os caracteres: {chars}").format(chars=" ".join(bad))
        )
    parts = path.split("/")[1:]
    if any(p in ("", ".", "..") for p in parts):
        raise ValidationError(_("O caminho da pasta não pode ter “.”, “..” ou barras duplas."))
    if path == "/":
        raise ValidationError(_("Escolha uma pasta, não a raiz do sistema."))
    for prefix in FORBIDDEN_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            raise ValidationError(
                _("Essa pasta pertence ao sistema ({prefix}). Escolha uma pasta sua.").format(prefix=prefix)
            )
    if path == "/run" or (path.startswith("/run/") and not path.startswith("/run/media/")):
        raise ValidationError(_("Pastas em /run são temporárias. Escolha um disco de verdade."))
    return path


def is_valid_version(tag: str) -> bool:
    return bool(VERSION_RE.match(tag))


def parse_version(tag: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(tag)
    if not match:
        raise ValidationError(_("Versão inválida: {tag}").format(tag=tag))
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def is_valid_uuid(value: str) -> bool:
    return bool(UUID_RE.match(value))


def is_valid_timezone(tz: str, zoneinfo: Path = Path("/usr/share/zoneinfo")) -> bool:
    if not TIMEZONE_RE.match(tz):
        return False
    return (zoneinfo / tz).is_file()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


@dataclass(frozen=True)
class PasswordStrength:
    score: int  # 0 a 4
    label: str


def password_strength(password: str) -> PasswordStrength:
    """Estimativa simples e honesta, sem dependências externas."""
    if not password:
        return PasswordStrength(0, "")
    score = 0
    length = len(password)
    if length >= 8:
        score += 1
    if length >= 12:
        score += 1
    classes = sum(
        (
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        )
    )
    if classes >= 3:
        score += 1
    if length >= 16 or (length >= 12 and classes == 4):
        score += 1
    if len(set(password)) <= 3 or password.lower() in COMMON_PASSWORDS:
        score = 0
    score = min(score, 4)
    labels = {
        0: _("muito fraca"),
        1: _("fraca"),
        2: _("razoável"),
        3: _("boa"),
        4: _("excelente"),
    }
    return PasswordStrength(score, labels[score])


COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "senha123",
        "password",
        "qwertyui",
        "immich123",
        "admin123",
        "abcdefgh",
    }
)
