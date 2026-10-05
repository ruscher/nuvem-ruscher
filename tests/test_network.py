"""Endereço para o celular e diagnóstico de conexão (funções puras)."""

import json

import pytest

from nuvem_ruscher.core import network
from nuvem_ruscher.core.network import AddressKind, Facts, address_kind, choose_lan_address, diagnose


@pytest.mark.parametrize(
    ("host", "kind"),
    [
        ("192.168.0.10", AddressKind.PRIVATE),
        ("10.1.2.3", AddressKind.PRIVATE),
        ("172.20.0.5", AddressKind.PRIVATE),
        ("100.100.184.97", AddressKind.TAILSCALE),
        ("ruscher-big.tail9c419a.ts.net", AddressKind.TAILSCALE),
        ("127.0.0.1", AddressKind.LOOPBACK),
        ("169.254.10.2", AddressKind.LINK_LOCAL),
        ("8.8.8.8", AddressKind.PUBLIC),
        ("nuvem.local", AddressKind.NAME),
        ("", AddressKind.INVALID),
        ("não é host", AddressKind.INVALID),
    ],
)
def test_address_kind(host, kind):
    assert address_kind(host) is kind


IP_ADDR = json.dumps(
    [
        {"ifname": "wlan0", "addr_info": [{"family": "inet", "local": "192.168.0.10"}]},
        {"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1"}]},
        {"ifname": "tun0", "addr_info": [{"family": "inet", "local": "10.8.0.2"}]},
        {"ifname": "tailscale0", "addr_info": [{"family": "inet", "local": "100.100.184.97"}]},
    ]
)


def test_parse_ip_addr():
    assert ("wlan0", "192.168.0.10") in network.parse_ip_addr(IP_ADDR)
    assert network.parse_ip_addr("não é json") == []


def test_default_route_on_home_network_wins():
    assert choose_lan_address("192.168.0.10", network.parse_ip_addr(IP_ADDR)) == "192.168.0.10"


def test_vpn_default_route_falls_back_to_the_home_network():
    # Com a VPN (tun0) como rota padrão, o celular não alcança 10.8.0.2.
    assert choose_lan_address("10.8.0.2", network.parse_ip_addr(IP_ADDR)) == "192.168.0.10"
    assert choose_lan_address("100.100.184.97", network.parse_ip_addr(IP_ADDR)) == "192.168.0.10"


def test_no_network_gives_loopback():
    assert choose_lan_address("", []) == "127.0.0.1"
    only_virtual = [("docker0", "172.17.0.1")]
    assert choose_lan_address("", only_virtual) == "127.0.0.1"


def facts(**kw):
    base = {"mode": "home", "host": "192.168.0.10", "server_local": True, "server_at_address": True}
    base.update(kw)
    return Facts(**base)


def test_everything_answers():
    result = diagnose(facts())
    assert result.ok and result.answers_here and result.problems == []


def test_server_off():
    result = diagnose(facts(server_local=False, server_at_address=False))
    assert not result.ok and result.problems == ["server-off"]


def test_no_network():
    assert diagnose(facts(host="127.0.0.1", server_at_address=False)).problems == ["no-network"]


def test_not_answering_on_the_network_address():
    assert diagnose(facts(server_at_address=False)).problems == ["not-answering"]


def test_firewall_is_a_warning_not_a_failure():
    result = diagnose(facts(firewall="ufw"))
    assert result.ok and result.warnings == ["firewall"]
    assert diagnose(facts(firewall="ufw", firewall_opened=True)).problems == []


def test_away_needs_tailscale():
    missing = diagnose(facts(mode="away", host="192.168.0.10"))
    assert missing.problems == ["tailscale-missing"]
    off = diagnose(facts(mode="away", host="192.168.0.10", tailscale_installed=True))
    assert off.problems == ["tailscale-off"]
    ready = diagnose(facts(mode="away", host="x.tail9c419a.ts.net", tailscale_installed=True, tailscale_running=True))
    assert ready.ok
    # O firewall da rede de casa não se aplica ao caminho do Tailscale.
    assert diagnose(
        facts(mode="away", host="100.100.184.97", tailscale_installed=True, tailscale_running=True, firewall="ufw")
    ).ok
