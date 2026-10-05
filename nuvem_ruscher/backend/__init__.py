"""Escolha do backend: real ou simulado."""

from __future__ import annotations

from nuvem_ruscher.backend.base import Backend


def create_backend(simulate: bool, scenario: str = "fresh") -> Backend:
    if simulate:
        from nuvem_ruscher.backend.simulated import SimulatedBackend

        return SimulatedBackend(scenario)
    from nuvem_ruscher.backend.real import RealBackend

    return RealBackend()
