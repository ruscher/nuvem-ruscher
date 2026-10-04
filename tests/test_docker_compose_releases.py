import json

from conftest import fixture_text

from nuvem_ruscher.core import compose, docker, helper_protocol, releases, system
from nuvem_ruscher.core.config import UserState, parse_conf
from nuvem_ruscher.core.docker import GroupAccess, Health


class TestDocker:
    def test_parse_ps(self):
        states = docker.parse_ps(fixture_text("docker-ps.jsonl").splitlines())
        assert [s.name for s in states] == [
            "immich_server",
            "immich_machine_learning",
            "immich_postgres",
            "immich_redis",
        ]
        server, ml, db, redis = states
        assert server.health is Health.HEALTHY and server.ok
        assert ml.health is Health.STARTING and not ml.ok
        assert db.health is Health.UNHEALTHY and not db.ok
        assert redis.state == "exited" and not redis.running

    def test_health_from_status_when_field_missing(self):
        line = json.dumps(
            {"Names": "immich_server", "State": "running", "Status": "Up 1 minute (health: starting)"}
        )
        assert docker.parse_ps([line])[0].health is Health.STARTING

    def test_parse_stats(self):
        stats = docker.parse_stats(fixture_text("docker-stats.jsonl").splitlines())
        assert stats["immich_server"].cpu_percent == 2.15
        assert stats["immich_server"].memory_bytes == int(410.5 * 1024**2)
        assert stats["immich_machine_learning"].memory_bytes == int(1.104 * 1024**3)
        assert stats["immich_postgres"].cpu_percent == 0.0

    def test_parse_events(self):
        events = [docker.parse_event(x) for x in fixture_text("docker-events.jsonl").splitlines()]
        assert events[0] == docker.DockerEvent("immich_server", "start")
        assert events[1].action == "health_status: healthy"
        assert docker.parse_event("lixo") is None

    def test_sg_wrapper_quotes_arguments(self):
        argv = docker.docker_argv(["logs", "immich_server"], GroupAccess.PENDING)
        assert argv == ["sg", "docker", "-c", "docker logs immich_server"]
        argv = docker.docker_argv(["compose", "--project-directory", "/a b/c"], GroupAccess.PENDING)
        assert argv[-1] == "docker compose --project-directory '/a b/c'"
        assert docker.docker_argv(["ps"], GroupAccess.ACTIVE) == ["docker", "ps"]

    def test_group_access_pending(self, monkeypatch):
        import grp

        fake = grp.struct_group(("docker", "x", 4242, ["ruscher"]))
        monkeypatch.setattr(grp, "getgrnam", lambda name: fake)
        monkeypatch.setattr(docker.os, "getuid", lambda: 1000)
        assert docker.docker_group_access("ruscher", [1007]) is GroupAccess.PENDING
        assert docker.docker_group_access("ruscher", [1007, 4242]) is GroupAccess.ACTIVE
        assert docker.docker_group_access("outro", [1007]) in (GroupAccess.MISSING, GroupAccess.PENDING)

    def test_logs_only_known_containers(self):
        assert docker.logs_args("immich_server")[-1] == "immich_server"
        try:
            docker.logs_args("; rm -rf /")
        except ValueError:
            pass
        else:
            raise AssertionError("container arbitrário aceito")


class TestPullProgress:
    def lines(self):
        events = [
            {"id": "immich-server", "status": "Working", "text": "Pulling"},
            {"id": "l1", "parent_id": "immich-server", "status": "Working", "text": "Pulling fs layer"},
            {
                "id": "l2",
                "parent_id": "immich-server",
                "status": "Done",
                "text": "Already exists",
                "percent": 100,
            },
            {
                "id": "l1",
                "parent_id": "immich-server",
                "status": "Working",
                "text": "Downloading",
                "current": 50,
                "total": 200,
            },
            {
                "id": "l1",
                "parent_id": "immich-server",
                "status": "Working",
                "text": "Downloading",
                "current": 150,
                "total": 200,
            },
            {"id": "l1", "parent_id": "immich-server", "status": "Done", "text": "Download complete"},
            {
                "id": "l1",
                "parent_id": "immich-server",
                "status": "Working",
                "text": "Extracting",
                "current": 10,
                "total": 200,
            },
            {"id": "l1", "parent_id": "immich-server", "status": "Done", "text": "Pull complete"},
            {"id": "immich-server", "status": "Done", "text": "Pulled"},
        ]
        return [json.dumps(e) for e in events]

    def test_progress_is_monotonic_and_complete(self):
        progress = compose.PullProgress()
        seen = []
        for i, line in enumerate(self.lines()):
            assert progress.feed(line, now=float(i))
            seen.append(progress.fraction)
        assert seen == sorted(seen)
        assert progress.downloaded == 200
        assert progress.total == 200
        assert progress.services["immich-server"] == "Pulled"
        assert progress.speed() > 0
        progress.finish()
        assert progress.fraction == 1.0

    def test_error_is_collected(self):
        progress = compose.PullProgress()
        progress.feed(
            json.dumps(
                {"id": "x", "parent_id": "s", "status": "Error", "text": "falhou", "details": "timeout"}
            )
        )
        assert progress.errors == ["timeout"]
        assert not progress.feed("texto comum")

    def test_pull_plan_has_no_secret(self, tmp_path):
        env = {"UPLOAD_LOCATION": "/run/media/ruscher/Novo volume/immich-ruscher", "IMMICH_VERSION": "v3.2.4"}
        plan = compose.write_pull_plan(tmp_path / "plano", "name: immich\n", "services: {}\n", env)
        text = (plan / ".env").read_text()
        assert 'UPLOAD_LOCATION="/run/media/ruscher/Novo volume/immich-ruscher"' in text
        assert f"DB_PASSWORD={compose.PLACEHOLDER_PASSWORD}" in text
        assert oct((plan / ".env").stat().st_mode & 0o777) == "0o600"


class TestReleases:
    def test_parse_skips_prereleases(self):
        rels = releases.parse_releases(fixture_text("releases.json"))
        assert [r.tag for r in rels] == ["v3.2.4", "v3.2.2", "v3.1.0", "v3.0.3", "v3.0.0"]

    def test_breaking_detection(self):
        rels = {r.tag: r for r in releases.parse_releases(fixture_text("releases.json"))}
        assert rels["v3.1.0"].has_breaking
        assert not rels["v3.2.4"].has_breaking

    def test_update_info(self):
        rels = releases.parse_releases(fixture_text("releases.json"))
        info = releases.update_info("v3.0.3", rels)
        assert info.available
        assert [r.tag for r in info.pending] == ["v3.2.4", "v3.2.2", "v3.1.0"]
        assert any(tag == "v3.1.0" for tag, _ in info.breaking)
        assert not info.major_change
        assert releases.update_info("v2.7.5", rels).major_change
        assert not releases.update_info("v3.2.4", rels).available

    def test_markdown_is_escaped(self):
        out = releases.simple_markdown_to_pango("## Novidades\n* <b>x</b> & **forte** `cod`")
        assert "&lt;b&gt;" in out
        assert "<b>forte</b>" in out
        assert "<tt>cod</tt>" in out


class TestSystem:
    def test_meminfo(self):
        assert system.parse_meminfo("MemTotal:       48675748 kB\nMemFree: 1 kB") == 48675748 * 1024

    def test_x86_64_v2(self):
        good = "flags\t\t: fpu cx16 lahf_lm popcnt sse4_1 sse4_2 ssse3 avx2"
        bad = "flags\t\t: fpu cx16 ssse3"
        assert system.cpu_supports_x86_64_v2(good)
        assert not system.cpu_supports_x86_64_v2(bad)
        assert system.cpu_supports_x86_64_v2("Features: fp asimd")

    def test_tailscale(self):
        text = json.dumps(
            {
                "BackendState": "Running",
                "Self": {"DNSName": "pc.tail.ts.net.", "TailscaleIPs": ["100.1.2.3", "fd7a::1"]},
            }
        )
        info = system.parse_tailscale_status(text)
        assert info.running and info.ip == "100.1.2.3" and info.dns_name == "pc.tail.ts.net"

    def test_gpu_detection(self, tmp_path):
        drm = tmp_path / "drm"
        for card, vendor in (("card0", "0x1002"), ("card1", "0x8086")):
            (drm / card / "device").mkdir(parents=True)
            (drm / card / "device" / "vendor").write_text(vendor + "\n")
        (drm / "card0-DP-1").mkdir()
        dri = tmp_path / "dri"
        dri.mkdir()
        (dri / "renderD128").write_text("")
        gpu = system.detect_gpu(drm, dri)
        assert gpu.vendors == ("amd", "intel")
        assert gpu.transcode == "quicksync"
        assert "openvino" in gpu.ml_options

    def test_port_status_detects_busy_port(self):
        import socket

        with socket.socket() as sock:
            sock.bind(("0.0.0.0", 0))
            sock.listen()
            port = sock.getsockname()[1]
            assert not system.port_status(port).free

    def test_timezones(self):
        zones = system.list_timezones()
        if zones:
            assert "America/Sao_Paulo" in zones


class TestConfigAndProtocol:
    def test_conf_keeps_spaces(self):
        conf = parse_conf(
            "# comentário\nINSTALLED=1\nUPLOAD_LOCATION=/run/media/ruscher/Novo volume/immich-ruscher\n"
            "MOUNT_UNIT=run-media-ruscher-Novo\\x20volume.mount\nIMMICH_VERSION=v3.2.4\n"
        )
        assert conf.installed
        assert conf.upload_location == "/run/media/ruscher/Novo volume/immich-ruscher"
        assert conf.mount_unit == "run-media-ruscher-Novo\\x20volume.mount"

    def test_user_state_is_private(self, tmp_path):
        state = UserState(tmp_path / "cfg" / "state.json")
        state.set("wizard_done", True)
        again = UserState(tmp_path / "cfg" / "state.json")
        assert again.get("wizard_done") is True
        assert oct((tmp_path / "cfg" / "state.json").stat().st_mode & 0o777) == "0o600"

    def test_protocol(self):
        p = helper_protocol.parse_line
        assert p("@@STEP download").kind == "step"
        assert p("@@RESULT file=/a b/c.sql.gz") == helper_protocol.HelperEvent(
            "result", "file", "/a b/c.sql.gz"
        )
        err = p("@@ERROR storage-missing disco ausente")
        assert (err.kind, err.key, err.value) == ("error", "storage-missing", "disco ausente")
        assert p("texto livre").kind == "log"
        title, hint = helper_protocol.human_error("codigo-que-nao-existe")
        assert title and hint
        assert helper_protocol.pkexec_error_code(126) == "auth-cancelled"
