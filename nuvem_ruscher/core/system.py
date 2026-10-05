"""Informações do sistema para a verificação inicial. Tudo só leitura, sem root."""

from __future__ import annotations

import errno
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from nuvem_ruscher.core import network

GIB = 1024**3


def run_text(argv: list[str], timeout: float = 10) -> tuple[int, str]:
    """Executa um comando curto e devolve (código, saída). Nunca usa shell."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_meminfo(text: str) -> int:
    """Memória total em bytes a partir de /proc/meminfo."""
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return 0


def mem_total() -> int:
    try:
        return parse_meminfo(Path("/proc/meminfo").read_text())
    except OSError:
        return 0


X86_64_V2_FLAGS = frozenset({"cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3"})


def cpu_supports_x86_64_v2(cpuinfo: str) -> bool:
    """Exigência do ML do Immich v3 em amd64 (docs/install/requirements)."""
    for line in cpuinfo.splitlines():
        if line.startswith("flags"):
            flags = set(line.split(":", 1)[1].split())
            return X86_64_V2_FLAGS.issubset(flags)
    # arm64 e outros não têm a linha "flags" no mesmo formato.
    return True


def cpu_info() -> tuple[int, bool]:
    cores = os.cpu_count() or 1
    try:
        v2 = cpu_supports_x86_64_v2(Path("/proc/cpuinfo").read_text())
    except OSError:
        v2 = True
    return cores, v2


def free_bytes(path: str) -> int:
    """Espaço livre para o usuário comum (``f_bavail``) no sistema de arquivos de ``path``."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        st = os.statvfs(probe)
    except OSError:
        return 0
    return st.f_bavail * st.f_frsize


def disk_usage(path: str) -> tuple[int, int, int]:
    """(total, usado, livre) em bytes."""
    try:
        st = os.statvfs(path)
    except OSError:
        return 0, 0, 0
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    return total, used, free


@dataclass(frozen=True)
class PortStatus:
    free: bool
    owner: str = ""  # processo, se identificável


def port_status(port: int) -> PortStatus:
    """Tenta ocupar a porta por um instante (não exige root para portas > 1024)."""
    for family, host in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                sock.bind((host, port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return PortStatus(False, port_owner(port))
            if exc.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                continue
            return PortStatus(False, str(exc))
    return PortStatus(True)


def port_owner(port: int) -> str:
    code, out = run_text(["ss", "-ltnpH", f"sport = :{port}"])
    if code != 0:
        return ""
    for line in out.splitlines():
        if "users:((" in line:
            return line.split("users:((", 1)[1].split(",", 1)[0].strip('"')
    return "docker-proxy" if out.strip() else ""


def check_internet(url: str, timeout: float = 6) -> bool:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "nuvem-ruscher"})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # o servidor respondeu — há internet
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def system_timezone() -> str:
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        target = ""
    if "zoneinfo/" in target:
        return target.split("zoneinfo/", 1)[1]
    code, out = run_text(["timedatectl", "show", "-p", "Timezone", "--value"])
    return out.strip() if code == 0 and out.strip() else "Etc/UTC"


def list_timezones(zoneinfo: Path = Path("/usr/share/zoneinfo")) -> list[str]:
    """Fusos conhecidos, a partir do tzdata (sem chamar timedatectl)."""
    tab = zoneinfo / "tzdata.zi"
    zones: set[str] = set()
    try:
        for line in tab.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "Z":
                zones.add(parts[1])
            elif len(parts) >= 3 and parts[0] == "L":
                zones.add(parts[2])
    except OSError:
        pass
    return sorted(z for z in zones if "/" in z and not z.startswith(("Etc/", "SystemV/")))


VENDORS = {"0x8086": "intel", "0x1002": "amd", "0x10de": "nvidia"}


@dataclass(frozen=True)
class GpuInfo:
    vendors: tuple[str, ...]
    render_node: bool
    nvidia_toolkit: bool

    @property
    def transcode(self) -> str:
        """Modo de transcodificação sugerido (serviço do hwaccel.transcoding.yml)."""
        if "intel" in self.vendors and self.render_node:
            return "quicksync"
        if "amd" in self.vendors and self.render_node:
            return "vaapi"
        if "nvidia" in self.vendors and self.nvidia_toolkit:
            return "nvenc"
        return "cpu"

    @property
    def ml_options(self) -> tuple[str, ...]:
        options = ["cpu"]
        if "intel" in self.vendors and self.render_node:
            options.append("openvino")
        if "amd" in self.vendors and Path("/dev/kfd").exists():
            options.append("rocm")
        if "nvidia" in self.vendors and self.nvidia_toolkit:
            options.append("cuda")
        return tuple(options)


def detect_gpu(sys_drm: Path = Path("/sys/class/drm"), dev_dri: Path = Path("/dev/dri")) -> GpuInfo:
    vendors: list[str] = []
    try:
        cards = sorted(p for p in sys_drm.iterdir() if p.name.startswith("card") and "-" not in p.name)
    except OSError:
        cards = []
    for card in cards:
        try:
            vendor = VENDORS.get((card / "device" / "vendor").read_text().strip())
        except OSError:
            vendor = None
        if vendor and vendor not in vendors:
            vendors.append(vendor)
    try:
        render = any(p.name.startswith("renderD") for p in dev_dri.iterdir())
    except OSError:
        render = False
    toolkit = bool(shutil.which("nvidia-ctk") or shutil.which("nvidia-container-runtime"))
    return GpuInfo(tuple(vendors), render, toolkit)


def lan_ip() -> str:
    """IP deste computador na rede de casa (sem enviar pacotes: só escolhe a rota).

    Com uma VPN como rota padrão, usa o endereço privado de uma interface de verdade.
    """
    route_ip = ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1, nunca roteado de verdade
            route_ip = str(sock.getsockname()[0] or "")
    except OSError:
        pass
    code, out = run_text(["ip", "-j", "-4", "addr", "show", "scope", "global"])
    addresses = network.parse_ip_addr(out) if code == 0 else []
    return network.choose_lan_address(route_ip, addresses)


@dataclass(frozen=True)
class TailscaleInfo:
    installed: bool
    running: bool = False
    ip: str = ""
    dns_name: str = ""


def parse_tailscale_status(text: str) -> TailscaleInfo:
    try:
        data = json.loads(text)
    except ValueError:
        return TailscaleInfo(True)
    me = data.get("Self") or {}
    ips = [ip for ip in me.get("TailscaleIPs") or [] if ":" not in ip]
    running = data.get("BackendState") == "Running"
    return TailscaleInfo(True, running, ips[0] if ips else "", str(me.get("DNSName") or "").rstrip("."))


def tailscale_info() -> TailscaleInfo:
    if not shutil.which("tailscale"):
        return TailscaleInfo(False)
    code, out = run_text(["tailscale", "status", "--json"], timeout=5)
    if code != 0 and not out.strip().startswith("{"):
        return TailscaleInfo(True)
    return parse_tailscale_status(out)


@dataclass(frozen=True)
class FirewallInfo:
    name: str  # "ufw", "firewalld" ou ""

    @property
    def active(self) -> bool:
        return bool(self.name)


def firewall_info() -> FirewallInfo:
    for name in ("ufw", "firewalld"):
        code, out = run_text(["systemctl", "is-active", f"{name}.service"], timeout=5)
        if code == 0 and out.strip() == "active":
            return FirewallInfo(name)
    return FirewallInfo("")


def unit_active_state(unit: str) -> str:
    """active, activating, deactivating, inactive, failed…"""
    code, out = run_text(["systemctl", "is-active", unit], timeout=5)
    state = out.strip().splitlines()[-1] if out.strip() else "unknown"
    return state if code in (0, 3, 4) else "unknown"


def unit_enabled(unit: str) -> bool:
    code, _ = run_text(["systemctl", "is-enabled", unit], timeout=5)
    return code == 0


def is_mountpoint(path: str) -> bool:
    return os.path.ismount(path)
