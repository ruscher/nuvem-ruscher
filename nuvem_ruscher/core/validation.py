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

# Pastas que só agrupam outras pastas: escolher a própria pasta é quase sempre um engano
# (as fotos ficariam misturadas com as pastas de outras pessoas ou do sistema).
GROUPING_FOLDERS = ("/home", "/mnt", "/media", "/opt", "/srv", "/var", "/var/lib", "/run/media")
# Aqui, o primeiro nível é a casa de um usuário ou a pasta de discos de um usuário.
ONE_LEVEL_GROUPING = ("/home", "/run/media")

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
        raise ValidationError(_("Choose a folder for the photos."))
    path = normalize_path(path)
    if not path.startswith("/"):
        raise ValidationError(_("The folder path must start with “/”."))
    if len(path) > 1024:
        raise ValidationError(_("The folder path is too long."))
    if any(unicodedata.category(c) == "Cc" for c in path):
        raise ValidationError(_("The folder name has unsupported invisible characters."))
    bad = sorted(FORBIDDEN_PATH_CHARS.intersection(path))
    if bad:
        raise ValidationError(_("The folder name cannot contain the characters: {chars}").format(chars=" ".join(bad)))
    parts = path.split("/")[1:]
    if any(p in ("", ".", "..") for p in parts):
        raise ValidationError(_("The folder path cannot contain “.”, “..” or double slashes."))
    if path == "/":
        raise ValidationError(_("Choose a folder, not the system root."))
    for prefix in FORBIDDEN_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            raise ValidationError(
                _("This folder belongs to the system ({prefix}). Choose a folder of your own.").format(prefix=prefix)
            )
    if path == "/run" or (path.startswith("/run/") and not path.startswith("/run/media/")):
        raise ValidationError(_("Folders in /run are temporary. Choose a real disk."))
    parent = path.rsplit("/", 1)[0]
    if path in GROUPING_FOLDERS or parent in ONE_LEVEL_GROUPING:
        raise ValidationError(
            _("“{path}” holds other folders of the system or of other people. Choose a folder inside it.").format(
                path=path
            )
        )
    return path


def is_valid_version(tag: str) -> bool:
    return bool(VERSION_RE.match(tag))


def parse_version(tag: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(tag)
    if not match:
        raise ValidationError(_("Invalid version: {tag}").format(tag=tag))
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
        0: _("very weak"),
        1: _("weak"),
        2: _("fair"),
        3: _("good"),
        4: _("excellent"),
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
