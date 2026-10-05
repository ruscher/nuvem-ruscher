import shutil
import subprocess

import pytest
from conftest import MOUNTPOINT, PHOTO_PATH

from nuvem_ruscher.core import escaping, validation
from nuvem_ruscher.core.validation import ValidationError


class TestPhotoPath:
    def test_path_with_space_is_valid(self):
        assert validation.validate_photo_path(PHOTO_PATH) == PHOTO_PATH

    def test_trailing_slash_is_normalized(self):
        assert validation.validate_photo_path(PHOTO_PATH + "/") == PHOTO_PATH

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "relativo/fotos",
            "/",
            "/etc/fotos",
            "/usr",
            "/var/lib/docker/x",
            "/var/lib/nuvem-ruscher/immich",
            "/tmp/fotos",
            "/run/user/1000/fotos",
            "/run/media/a/../../etc",
            "/run/media/a/./b",
            "/run/media/a//b",
            '/run/media/a/"b',
            "/run/media/a/$(reboot)",
            "/run/media/a/`id`",
            "/run/media/a/b\\c",
            "/run/media/a/100%",
            "/run/media/a/linha\nnova",
            "/run/media/a/tab\tx",
            "/home",
            "/home/maria",
            "/home/maria/",
            "/run/media",
            "/run/media/maria",
            "/mnt",
            "/media",
            "/var",
            "/var/lib",
            "/opt",
            "/srv",
        ],
    )
    def test_rejected(self, path):
        with pytest.raises(ValidationError):
            validation.validate_photo_path(path)

    @pytest.mark.parametrize(
        "path",
        [
            "/home/ruscher/Imagens/Immich",
            "/mnt/Dados/immich",
            "/mnt/HD1",
            "/run/media/r/Ção é/fotos",
            "/run/media/r/Novo volume",
            "/srv/fotos",
        ],
    )
    def test_accepted(self, path):
        assert validation.validate_photo_path(path) == path


def test_version_parsing():
    assert validation.parse_version("v3.2.4") == (3, 2, 4)
    assert not validation.is_valid_version("v3")
    assert not validation.is_valid_version("3.2.4")
    assert not validation.is_valid_version("v3.3.0-rc.1")
    assert not validation.is_valid_version("v3.2.4; reboot")


def test_uuid_and_timezone():
    assert validation.is_valid_uuid("F22A6D342A6CF74F")
    assert validation.is_valid_uuid("12a560b3-9605-43c2-94f4-17b722d70d60")
    assert not validation.is_valid_uuid("../../etc")
    assert not validation.is_valid_uuid("ABC")
    assert validation.is_valid_timezone("America/Sao_Paulo")
    assert not validation.is_valid_timezone("../../etc/passwd")
    assert not validation.is_valid_timezone("America/Nao_Existe")


def test_email_and_password():
    assert validation.is_valid_email("voce@exemplo.com.br")
    assert not validation.is_valid_email("voce@exemplo")
    assert not validation.is_valid_email("sem arroba.com")
    assert validation.password_strength("").score == 0
    assert validation.password_strength("12345678").score == 0
    assert validation.password_strength("aaaaaaaaaaaa").score == 0
    assert validation.password_strength("Fotos-da-Familia-2026!").score == 4
    weak = validation.password_strength("abc12345")
    assert 0 < weak.score < 3


class TestFstabEscape:
    def test_space(self):
        assert escaping.fstab_escape(MOUNTPOINT) == "/run/media/ruscher/Novo\\040volume"

    def test_roundtrip(self):
        for path in (MOUNTPOINT, "/a\tb", "/a\\b", "/sem_espaco", "/Ção é"):
            assert escaping.fstab_unescape(escaping.fstab_escape(path)) == path

    def test_unescape_keeps_plain_backslash(self):
        assert escaping.fstab_unescape("/a\\x") == "/a\\x"


class TestSystemdEscape:
    CASES = (
        MOUNTPOINT,
        "/mnt/my-disk",
        "/home",
        "/",
        "/run/media/a/.hidden",
        "/run/media/r/Dados_2.0",
        "/run/media/r/Ção",
        "/run/media/r/a:b",
        "/.oculto/x",
    )

    def test_known_value(self):
        assert escaping.mount_unit_name(MOUNTPOINT) == "run-media-ruscher-Novo\\x20volume.mount"

    @pytest.mark.skipif(not shutil.which("systemd-escape"), reason="systemd-escape ausente")
    @pytest.mark.parametrize("path", CASES)
    def test_matches_systemd_escape(self, path):
        expected = subprocess.run(
            ["systemd-escape", "-p", "--suffix=mount", path], capture_output=True, text=True, check=True
        ).stdout.strip()
        assert escaping.mount_unit_name(path) == expected

    def test_quote(self):
        assert escaping.systemd_quote(PHOTO_PATH) == f'"{PHOTO_PATH}"'
        with pytest.raises(ValueError):
            escaping.systemd_quote('/a"b')
        with pytest.raises(ValueError):
            escaping.systemd_quote("/a%b")
