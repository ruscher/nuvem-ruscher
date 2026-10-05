"""Endereços para o celular e o diagnóstico de “o celular não acha o servidor”.

Funções puras (sem rede, sem GTK): quem coleta os fatos é o backend. O teste que o app
faz roda **neste computador**; ele prova que o servidor responde no endereço, não que o
celular alcança esse endereço. A interface diz isso com essas palavras.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, field
from enum import Enum

# Interfaces que não são a rede de casa: VPNs, containers, máquinas virtuais.
VIRTUAL_PREFIXES = (
    "docker",
    "br-",
    "veth",
    "tailscale",
    "virbr",
    "tun",
    "tap",
    "wg",
    "ppp",
    "zt",
    "vboxnet",
    "vmnet",
    "lxc",
    "lxd",
    "incus",
    "podman",
    "cni",
    "flannel",
)
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


class AddressKind(Enum):
    PRIVATE = "private"  # 192.168.x.x, 10.x.x.x, 172.16–31.x.x: rede de casa
    TAILSCALE = "tailscale"  # 100.64.0.0/10 ou nome *.ts.net
    LOOPBACK = "loopback"  # 127.x: só este computador
    LINK_LOCAL = "link-local"  # 169.254.x.x: rede sem roteador respondendo
    PUBLIC = "public"
    NAME = "name"  # um nome qualquer (DNS)
    INVALID = "invalid"


def address_kind(host: str) -> AddressKind:
    host = host.strip().strip("[]")
    if not host:
        return AddressKind.INVALID
    if host.endswith(".ts.net"):
        return AddressKind.TAILSCALE
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return AddressKind.NAME if all(part for part in host.split(".")) and " " not in host else AddressKind.INVALID
    if ip.is_loopback or ip.is_unspecified:
        return AddressKind.LOOPBACK
    if ip.is_link_local:
        return AddressKind.LINK_LOCAL
    if ip.version == 4 and ip in TAILSCALE_NET:
        return AddressKind.TAILSCALE
    if ip.is_private:
        return AddressKind.PRIVATE
    return AddressKind.PUBLIC


def is_virtual(interface: str) -> bool:
    return interface.startswith(VIRTUAL_PREFIXES) or interface == "lo"


def parse_ip_addr(text: str) -> list[tuple[str, str]]:
    """``ip -j -4 addr`` → [(interface, ipv4)]."""
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return []
    found = []
    for iface in data if isinstance(data, list) else []:
        name = str(iface.get("ifname", "")) if isinstance(iface, dict) else ""
        for addr in iface.get("addr_info", []) if isinstance(iface, dict) else []:
            if isinstance(addr, dict) and addr.get("family") == "inet" and addr.get("local"):
                found.append((name, str(addr["local"])))
    return found


def choose_lan_address(route_ip: str, addresses: list[tuple[str, str]]) -> str:
    """O endereço que um celular na mesma rede usa para chegar a este computador.

    ``route_ip`` é o endereço da rota padrão. Com uma VPN ligada, ele é o da VPN, que o
    celular não alcança; aí vale o endereço privado de uma interface de verdade.
    """
    by_ip = {ip: name for name, ip in addresses}
    route_iface = by_ip.get(route_ip, "")
    if route_ip and address_kind(route_ip) is AddressKind.PRIVATE and not is_virtual(route_iface):
        return route_ip
    for name, ip in addresses:
        if not is_virtual(name) and address_kind(ip) is AddressKind.PRIVATE:
            return ip
    if route_ip and address_kind(route_ip) not in (AddressKind.LOOPBACK, AddressKind.INVALID):
        return route_ip
    for name, ip in addresses:
        if not is_virtual(name) and address_kind(ip) not in (AddressKind.LOOPBACK, AddressKind.INVALID):
            return ip
    return "127.0.0.1"


# --- diagnóstico ---------------------------------------------------------------------------

# Códigos de problema, do mais para o menos grave. O texto humano fica na interface.
PROBLEMS = (
    "server-off",  # o servidor não responde nem neste computador
    "no-network",  # este computador não está em rede nenhuma
    "link-local",  # rede sem roteador (169.254.x.x)
    "tailscale-missing",  # fora de casa: Tailscale não instalado neste computador
    "tailscale-off",  # fora de casa: Tailscale desligado neste computador
    "not-answering",  # responde em localhost, mas não no endereço mostrado
    "firewall",  # firewall ativo e a porta ainda não foi liberada pelo app
    "public-address",  # o endereço não parece ser de uma rede de casa
)
# Avisos: o teste daqui não enxerga esses casos, então não reprovam o endereço.
WARNINGS = frozenset({"firewall", "public-address"})


@dataclass(frozen=True)
class Facts:
    mode: str  # "home" | "away"
    host: str  # o host do endereço mostrado no QR
    server_local: bool  # responde em http://localhost:2283
    server_at_address: bool  # responde no endereço do QR (testado daqui)
    firewall: str = ""  # "ufw", "firewalld" ou ""
    firewall_opened: bool = False  # o app já liberou a porta
    tailscale_installed: bool = False
    tailscale_running: bool = False


@dataclass
class Diagnosis:
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """O servidor responde no endereço (visto deste computador); avisos não contam."""
        return not [p for p in self.problems if p not in WARNINGS]

    @property
    def warnings(self) -> list[str]:
        return [p for p in self.problems if p in WARNINGS]

    @property
    def answers_here(self) -> bool:
        return "server-off" not in self.problems and "not-answering" not in self.problems


def diagnose(facts: Facts) -> Diagnosis:
    problems: list[str] = []
    if not facts.server_local:
        problems.append("server-off")
    kind = address_kind(facts.host)
    if facts.mode == "away":
        if not facts.tailscale_installed:
            problems.append("tailscale-missing")
        elif not facts.tailscale_running or kind is not AddressKind.TAILSCALE:
            problems.append("tailscale-off")
    elif kind in (AddressKind.LOOPBACK, AddressKind.INVALID):
        problems.append("no-network")
    elif kind is AddressKind.LINK_LOCAL:
        problems.append("link-local")
    if facts.server_local and not facts.server_at_address and not {"no-network", "tailscale-missing"} & set(problems):
        problems.append("not-answering")
    # Do próprio computador o firewall não aparece no teste (o pacote não sai daqui).
    if facts.mode == "home" and facts.firewall and not facts.firewall_opened:
        problems.append("firewall")
    if facts.mode == "home" and kind is AddressKind.PUBLIC:
        problems.append("public-address")
    return Diagnosis([p for p in PROBLEMS if p in problems])
