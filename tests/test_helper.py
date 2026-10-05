"""Testes do helper privilegiado em modo simulado.

Cada teste roda o helper de verdade (Bash) numa raiz-sandbox **com espaço no nome**,
com comandos falsos para systemctl, docker, curl, blkid etc. (tests/sim-bin).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from conftest import FIXTURES, ROOT

from nuvem_ruscher import VERSION
from nuvem_ruscher.core import fstab as py_fstab
from nuvem_ruscher.core.helper_protocol import parse_line

HELPER = ROOT / "helper" / "nuvem-ruscher-helper"
SIM_BIN = Path(__file__).resolve().parent / "sim-bin"
UUID = "F22A6D342A6CF74F"
FSTAB_ORIGINAL = (FIXTURES / "fstab-biglinux.txt").read_text()


class Sim:
    def __init__(self, base: Path):
        self.root = base / "raiz com espaço"
        (self.root / "bin").mkdir(parents=True)
        for stub in SIM_BIN.iterdir():
            shutil.copy2(stub, self.root / "bin" / stub.name)
        (self.root / "etc").mkdir()
        (self.root / "etc" / "fstab").write_text(FSTAB_ORIGINAL)
        self.mountpoint = str(self.root / "run" / "media" / "ruscher" / "Novo volume")
        Path(self.mountpoint).mkdir(parents=True)
        self.photos = self.mountpoint + "/immich-ruscher"
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", "/tmp"),
            "NUVEM_RUSCHER_SIM_ROOT": str(self.root),
            "SIM_FIXTURES": str(FIXTURES),
            "SIM_MOUNTPOINT": self.mountpoint,
        }

    @property
    def stack(self) -> Path:
        return self.root / "var" / "lib" / "nuvem-ruscher" / "immich"

    @property
    def conf(self) -> Path:
        return self.root / "etc" / "nuvem-ruscher" / "nuvem-ruscher.conf"

    @property
    def unit(self) -> Path:
        return self.root / "etc" / "systemd" / "system" / "nuvem-ruscher-immich.service"

    @property
    def fstab(self) -> Path:
        return self.root / "etc" / "fstab"

    def run(self, *args: str, stdin: str = "", **extra_env: str) -> subprocess.CompletedProcess:
        env = {**self.env, **extra_env}
        return subprocess.run(
            ["bash", str(HELPER), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
            check=False,
        )

    def events(self, proc: subprocess.CompletedProcess):
        return [parse_line(line) for line in proc.stdout.splitlines()]

    def error(self, proc) -> str | None:
        errors = [e.key for e in self.events(proc) if e.kind == "error"]
        return errors[-1] if errors else None

    def results(self, proc) -> dict[str, str]:
        return {e.key: e.value for e in self.events(proc) if e.kind == "result"}

    def calls(self) -> list[str]:
        log = self.root / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def setup(self, *, version="v3.2.4", transcode="vaapi", ml="cpu", **env):
        proc = self.run("setup", version, self.photos, "America/Sao_Paulo", transcode, ml, **env)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return proc


@pytest.fixture
def sim():
    # Não usamos /tmp: em muitos sistemas (inclusive o BigLinux) ele é montado com
    # noexec, e os comandos falsos não poderiam ser executados.
    base = ROOT / "build" / "testes"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="helper-", dir=base))
    yield Sim(path)
    shutil.rmtree(path, ignore_errors=True)


def test_sandbox_refuses_real_commands(tmp_path):
    """Se os falsos não forem executáveis, o helper não pode cair nos reais."""
    sim = Sim(tmp_path)
    for stub in (sim.root / "bin").iterdir():
        stub.chmod(0o644)
    proc = sim.run("setup", "v3.2.4", sim.photos, "America/Sao_Paulo", "cpu", "cpu")
    assert proc.returncode == 1
    assert "incomplete sandbox" in proc.stdout
    assert not (sim.root / "var").exists()


def env_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


class TestSetup:
    def test_generates_everything(self, sim):
        proc = sim.setup()
        res = sim.results(proc)
        assert res["mountpoint"] == sim.mountpoint
        assert Path(sim.photos).is_dir()

        env_file = sim.stack / ".env"
        assert oct(env_file.stat().st_mode & 0o777) == "0o600"
        env = env_values(env_file)
        assert env["UPLOAD_LOCATION"] == f'"{sim.photos}"'
        assert env["IMMICH_VERSION"] == '"v3.2.4"'
        assert env["TZ"] == '"America/Sao_Paulo"'
        assert re.fullmatch(r'"[A-Za-z0-9]{32}"', env["DB_PASSWORD"])
        assert env["DB_DATA_LOCATION"] == f'"{sim.stack}/postgres"'

        compose = (sim.stack / "docker-compose.yml").read_text()
        assert compose == (FIXTURES / "immich-v3.2.4-docker-compose.yml").read_text(), "oficial alterado!"

        override = (sim.stack / "docker-compose.override.yml").read_text()
        assert override.count('restart: "no"') == 4
        assert override.count("          create_host_path: false\n") == 2
        assert "/dev/dri:/dev/dri" in override

        conf = sim.conf.read_text()
        assert f"UPLOAD_LOCATION={sim.photos}\n" in conf
        assert "MOUNT_UNIT=" in conf and "INSTALLED=1" in conf
        assert "DB_PASSWORD" not in conf

    def test_unit_quotes_paths_with_space(self, sim):
        sim.setup()
        unit = sim.unit.read_text()
        mount_unit = subprocess.run(
            ["systemd-escape", "-p", "--suffix=mount", sim.mountpoint],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert f"BindsTo={mount_unit}" in unit
        assert f'RequiresMountsFor="{sim.photos}" "{sim.stack}"' in unit
        assert f'ExecStartPre=/usr/bin/mountpoint -q "{sim.mountpoint}"' in unit
        assert "--pull never" in unit and "Restart=always" in unit
        assert "SuccessExitStatus=143" in unit  # desligar não deixa a unidade "failed"

    @pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="systemd-analyze ausente")
    def test_unit_passes_systemd_analyze(self, sim):
        sim.setup()
        out = subprocess.run(
            ["systemd-analyze", "verify", str(sim.unit)],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        text = out.stdout + out.stderr
        assert "not absolute" not in text
        assert "Failed to add dependency" not in text
        assert "Invalid" not in text

    @pytest.mark.skipif(not shutil.which("docker"), reason="docker CLI ausente")
    def test_compose_config_merges_override(self, sim):
        sim.setup()
        # Não precisa do daemon: só valida e mescla os arquivos gerados. JSON porque o
        # YAML de saída quebra linhas longas justamente nos espaços.
        proc = subprocess.run(
            ["docker", "compose", "--project-directory", str(sim.stack), "config", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        services = json.loads(proc.stdout)["services"]
        data = [v for v in services["immich-server"]["volumes"] if v["target"] == "/data"]
        assert len(data) == 1, "o /data oficial precisa ser substituído, não duplicado"
        assert data[0]["source"] == sim.photos
        assert data[0]["bind"]["create_host_path"] is False
        db = services["database"]["volumes"][0]
        assert db["source"] == str(sim.stack / "postgres") and db["bind"]["create_host_path"] is False
        assert all(svc.get("restart") == "no" for svc in services.values())
        assert services["immich-server"]["environment"]["UPLOAD_LOCATION"] == sim.photos
        assert services["immich-server"]["image"].endswith(":v3.2.4")
        # O servidor espera o banco saudável (o oficial só ordena a subida).
        depends = services["immich-server"]["depends_on"]
        assert depends["database"]["condition"] == "service_healthy"
        assert depends["redis"]["condition"] == "service_started"

    def test_second_setup_preserves_password(self, sim):
        sim.setup()
        first = env_values(sim.stack / ".env")["DB_PASSWORD"]
        sim.setup(transcode="cpu")
        assert env_values(sim.stack / ".env")["DB_PASSWORD"] == first

    def test_existing_database_without_env_stops(self, sim):
        sim.setup()
        (sim.stack / "postgres" / "PG_VERSION").write_text("14\n")
        (sim.stack / ".env").unlink()
        proc = sim.run("setup", "v3.2.4", sim.photos, "America/Sao_Paulo", "cpu", "cpu")
        assert sim.error(proc) == "db-password-missing"

    def test_disk_missing(self, sim):
        shutil.rmtree(sim.mountpoint)
        proc = sim.run("setup", "v3.2.4", sim.photos, "America/Sao_Paulo", "cpu", "cpu")
        assert sim.error(proc) == "storage-missing"
        assert not Path(sim.photos).exists(), "nunca criar a pasta sem o disco"

    def test_read_only_disk(self, sim):
        proc = sim.run("setup", "v3.2.4", sim.photos, "America/Sao_Paulo", "cpu", "cpu", SIM_OPTIONS="ro,nosuid")
        assert sim.error(proc) == "storage-unsafe"

    def test_ml_off_uses_profile(self, sim):
        sim.setup(ml="off", transcode="cpu")
        override = (sim.stack / "docker-compose.override.yml").read_text()
        assert 'profiles: ["desativado"]' in override
        assert "/dev/dri" not in override

    def test_download_failure_is_clean(self, sim):
        proc = sim.run("setup", "v3.2.4", sim.photos, "America/Sao_Paulo", "cpu", "cpu", SIM_DOWNLOAD_FAIL="1")
        assert sim.error(proc) == "download-failed"
        assert not (sim.stack / "docker-compose.yml").exists()


class TestValidation:
    @pytest.mark.parametrize(
        "args",
        [
            ("setup", "v3.2.4; reboot", "{photos}", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/run/media/x/$(id)", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/run/media/x/../../../etc", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/etc/fotos", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/home", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/home/maria", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/run/media/maria", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/var", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{root}/mnt", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "/fora/da/raiz", "America/Sao_Paulo", "cpu", "cpu"),
            ("setup", "v3.2.4", "{photos}", "../../etc/passwd", "cpu", "cpu"),
            ("setup", "v3.2.4", "{photos}", "America/Sao_Paulo", "rm -rf /", "cpu"),
            ("setup", "v3.2.4", "{photos}", "America/Sao_Paulo", "cpu", "gpu"),
            ("setup", "v3.2.4"),
            ("fstab-add", "../../x", "{mount}"),
            ("fstab-add", UUID, "{root}/usr/lib"),
            ("update", "latest"),
            ("uninstall", "-v"),
            ("start", "extra"),
            ("rodar-qualquer-coisa",),
        ],
    )
    def test_rejects(self, sim, args):
        filled = [a.format(photos=sim.photos, root=str(sim.root), mount=sim.mountpoint) for a in args]
        proc = sim.run(*filled)
        assert proc.returncode == 1
        assert sim.error(proc) in ("invalid-argument", "storage-unsafe")
        assert not sim.conf.exists()

    def test_rejects_symlink_inside_photo_path(self, sim):
        """Como root, o helper cria a pasta e a entrega ao usuário: não pode ser em /etc."""
        (sim.root / "etc" / "systemd").mkdir()
        Path(sim.mountpoint, "atalho").symlink_to(sim.root / "etc" / "systemd")
        proc = sim.run("setup", "v3.2.4", f"{sim.mountpoint}/atalho/fotos", "America/Sao_Paulo", "cpu", "cpu")
        assert sim.error(proc) == "storage-unsafe"
        assert not (sim.root / "etc" / "systemd" / "fotos").exists()
        assert not sim.conf.exists()

    def test_simulation_refused_under_pkexec(self, sim):
        proc = sim.run("setup", "v3.2.4", sim.photos, "America/Sao_Paulo", "cpu", "cpu", PKEXEC_UID="1000")
        assert sim.error(proc) == "not-authorized"
        assert not (sim.root / "calls.log").exists()

    def test_version_needs_no_root(self, sim):
        proc = sim.run("version")
        assert proc.returncode == 0 and proc.stdout.strip() == VERSION

    def test_no_recursive_removal_except_snapshot(self):
        text = HELPER.read_text()
        assert "rm -rf" not in text
        assert "rm -fr" not in text
        recursive = [line.strip() for line in text.splitlines() if re.search(r"\brm\b.*\s-r\b", line)]
        # Só duas remoções recursivas, ambas restritas a um sistema de arquivos e a caminhos
        # que o próprio helper conhece: o snapshot anterior do banco e as pastas do Immich
        # da cópia antiga, depois de uma migração verificada (remove-old-copy).
        assert recursive == [
            'rm -r --one-file-system --preserve-root=all -- "$SNAPSHOT_DIR"',
            'rm -r --one-file-system --preserve-root=all -- "./${folder:?}"',
        ]
        assert "down -v" not in text and "--volumes" not in text
        assert not re.search(r"(^|[;&|]\s*)\s*(eval|source|\.)\s", text, re.MULTILINE), "nada de eval/source"


class TestFstab:
    def test_add_and_remove_roundtrip(self, sim):
        proc = sim.run("fstab-add", UUID, sim.mountpoint)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        text = sim.fstab.read_text()
        assert text.startswith(FSTAB_ORIGINAL)
        added = text[len(FSTAB_ORIGINAL) :].splitlines()
        assert added[0].startswith(py_fstab.MARKER)
        escaped = sim.mountpoint.replace(" ", "\\040")
        assert added[1].startswith(f"UUID={UUID} {escaped} ntfs-3g ")
        backups = list((sim.root / "etc").glob("fstab.nuvem-ruscher-*.bak"))
        assert len(backups) == 1 and backups[0].read_text() == FSTAB_ORIGINAL

        again = sim.run("fstab-add", UUID, sim.mountpoint)
        assert sim.error(again) == "fstab-exists"

        removed = sim.run("fstab-remove", UUID)
        assert removed.returncode == 0, removed.stdout
        assert sim.fstab.read_text() == FSTAB_ORIGINAL

    def test_line_matches_python_preview(self, sim):
        sim.run("fstab-add", UUID, sim.mountpoint)
        line = sim.fstab.read_text().splitlines()[-1]
        uid, gid = os.getuid(), os.getgid()
        import pwd

        gid = pwd.getpwuid(uid).pw_gid
        assert line == py_fstab.fstab_line(UUID, sim.mountpoint, "ntfs", uid, gid)

    def test_verify_failure_keeps_original(self, sim):
        proc = sim.run("fstab-add", UUID, sim.mountpoint, SIM_VERIFY_FAIL="1")
        assert sim.error(proc) == "fstab-invalid"
        assert sim.fstab.read_text() == FSTAB_ORIGINAL

    def test_unit_check_failure_restores_backup(self, sim):
        proc = sim.run("fstab-add", UUID, sim.mountpoint, SIM_SOURCE_PATH="")
        assert sim.error(proc) == "fstab-invalid"
        assert sim.fstab.read_text() == FSTAB_ORIGINAL

    def test_unknown_uuid(self, sim):
        proc = sim.run("fstab-add", "ABCDEF123456", sim.mountpoint)
        assert sim.error(proc) == "storage-missing"

    def test_does_not_remove_foreign_entry(self, sim):
        foreign = FSTAB_ORIGINAL + f"UUID={UUID} /mnt/outro ntfs-3g defaults 0 0\n"
        sim.fstab.write_text(foreign)
        proc = sim.run("fstab-remove", UUID)
        assert sim.error(proc) == "fstab-invalid"
        assert sim.fstab.read_text() == foreign

    def test_enables_boot_start_after_fstab(self, sim):
        proc = sim.setup()
        assert sim.results(proc)["boot"] == "on-disk-mount"
        add = sim.run("fstab-add", UUID, sim.mountpoint)
        assert sim.results(add)["boot"] == "auto"
        assert any(c.startswith("systemctl enable nuvem-ruscher-immich.service") for c in sim.calls())
        wants = list((sim.root / "etc" / "systemd" / "system").glob("*.mount.wants/nuvem-ruscher-immich.service"))
        assert len(wants) == 1


class TestService:
    def test_start_requires_mounted_disk(self, sim):
        sim.setup()
        proc = sim.run("start", SIM_MOUNTED="0")
        assert sim.error(proc) == "storage-missing"
        ok = sim.run("start")
        assert ok.returncode == 0
        assert (sim.root / "state" / "service").read_text() == "active"

    def test_backup_goes_to_photo_disk_without_leftovers(self, sim):
        sim.setup()
        proc = sim.run("backup-db")
        assert proc.returncode == 0, proc.stdout
        path = Path(sim.results(proc)["file"])
        assert path.parent == Path(sim.photos) / "backups" / "nuvem-ruscher"
        assert path.name.endswith("-v3.2.4.sql.gz")
        subprocess.run(["gzip", "-t", str(path)], check=True)
        assert list((sim.root / "var" / "lib" / "nuvem-ruscher" / "tmp").iterdir()) == []

    def test_backup_does_not_follow_symlink_in_photo_folder(self, sim):
        sim.setup()
        target = sim.root / "etc" / "alvo"
        target.mkdir()
        Path(sim.photos, "backups").symlink_to(target)
        proc = sim.run("backup-db")
        assert sim.error(proc) == "storage-unsafe"
        assert list(target.iterdir()) == []
        assert list((sim.root / "var" / "lib" / "nuvem-ruscher" / "tmp").iterdir()) == []


class TestUpdate:
    def prepare(self, sim):
        sim.setup(version="v3.0.3")
        db = sim.stack / "postgres"
        (db / "PG_VERSION").write_text("14\n")
        (db / "dados").write_text("banco antigo")
        sim.run("start")

    def test_successful_update(self, sim):
        self.prepare(sim)
        proc = sim.run("update", "v3.2.4", SIM_SERVER_VERSION="v3.2.4")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert sim.results(proc)["version"] == "v3.2.4"
        assert 'IMMICH_VERSION="v3.2.4"' in (sim.stack / ".env").read_text()
        assert "IMMICH_VERSION=v3.2.4" in sim.conf.read_text()
        assert (sim.stack / "postgres.anterior" / "dados").read_text() == "banco antigo"
        steps = [e.value for e in sim.events(proc) if e.kind == "step"]
        assert steps.index("backup") < steps.index("stop") < steps.index("snapshot") < steps.index("switch")
        # Uma segunda atualização substitui o snapshot antigo (remoção guardada).
        sim.run("update", "v3.2.4")  # mesma versão: recusa
        assert sim.conf.read_text().count("IMMICH_VERSION=v3.2.4") == 1

    def test_failed_update_rolls_back(self, sim):
        self.prepare(sim)
        password = env_values(sim.stack / ".env")["DB_PASSWORD"]
        # O servidor continua respondendo como v3.0.3: a nova versão "não sobe".
        proc = sim.run("update", "v3.2.4", SIM_SERVER_VERSION="v3.0.3")
        assert sim.error(proc) == "update-rolled-back"
        assert "IMMICH_VERSION=v3.0.3" in sim.conf.read_text()
        env = env_values(sim.stack / ".env")
        assert env["IMMICH_VERSION"] == '"v3.0.3"' and env["DB_PASSWORD"] == password
        assert (sim.stack / "postgres" / "dados").read_text() == "banco antigo"
        failed = list(sim.stack.glob("postgres.falhou-*"))
        assert len(failed) == 1, "o banco da tentativa é guardado, nunca apagado"

    def test_pull_failure_changes_nothing(self, sim):
        self.prepare(sim)
        before = sim.conf.read_text()
        proc = sim.run("update", "v3.2.4", SIM_PULL_FAIL="1")
        assert sim.error(proc) == "download-failed"
        assert sim.conf.read_text() == before
        assert (sim.root / "state" / "service").read_text() == "active"

    def test_rejects_downgrade(self, sim):
        self.prepare(sim)
        proc = sim.run("update", "v2.7.5")
        assert sim.error(proc) == "invalid-argument"


class TestUninstall:
    def test_keeps_photos_database_and_secret(self, sim):
        sim.setup()
        (Path(sim.photos) / "foto.jpg").write_bytes(b"\xff\xd8")
        (sim.stack / "postgres" / "PG_VERSION").write_text("14\n")
        proc = sim.run("uninstall", "--remove-images")
        assert proc.returncode == 0, proc.stdout
        assert (Path(sim.photos) / "foto.jpg").exists()
        assert (sim.stack / "postgres" / "PG_VERSION").exists()
        assert (sim.stack / ".env").exists()
        assert not sim.unit.exists()
        assert not (sim.stack / "docker-compose.yml").exists()
        assert "INSTALLED=0" in sim.conf.read_text()
        downs = [c for c in sim.calls() if c.startswith("docker compose") and " down" in c]
        assert downs and all(" -v" not in c and "--volumes" not in c for c in downs)

    def test_reinstall_reuses_password(self, sim):
        sim.setup()
        password = env_values(sim.stack / ".env")["DB_PASSWORD"]
        sim.run("uninstall")
        sim.setup()
        assert env_values(sim.stack / ".env")["DB_PASSWORD"] == password


class TestSystemActions:
    def test_install_docker(self, sim):
        proc = sim.run("install-docker")
        assert proc.returncode == 0
        assert "pacman -S --needed --noconfirm docker docker-compose" in sim.calls()

    def test_install_docker_failure(self, sim):
        proc = sim.run("install-docker", SIM_FAIL_pacman="1")
        assert sim.error(proc) == "pacman-failed"

    def test_group_uses_calling_user(self, sim):
        import pwd

        proc = sim.run("add-docker-group")
        assert proc.returncode == 0
        user = pwd.getpwuid(os.getuid()).pw_name
        assert f"gpasswd -a {user} docker" in sim.calls()

    def test_firewall_only_local_networks(self, sim):
        proc = sim.run("firewall-allow", SIM_UFW="1")
        assert proc.returncode == 0
        rules = [c for c in sim.calls() if c.startswith("ufw allow")]
        assert len(rules) == 4
        assert all("port 2283 proto tcp" in r for r in rules)
        assert not any("from any" in r for r in rules)
