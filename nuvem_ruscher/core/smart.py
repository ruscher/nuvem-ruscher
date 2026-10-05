"""Saúde dos discos pelo SMART (saída JSON do ``smartctl -j``).

O ``smartctl`` precisa de root: quem o roda é o helper (ação ``disk-health``); aqui só se
interpreta a saída. O resultado é sempre explicável: nível + motivos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Atributos ATA que indicam desgaste físico (id → nome curto).
REALLOCATED = 5
PENDING = 197
UNCORRECTABLE = 198
# Temperaturas a partir das quais vale avisar (°C).
HOT_HDD = 55
HOT_SSD = 70


@dataclass
class SmartInfo:
    device: str
    available: bool = False  # SMART lido com sucesso
    passed: bool | None = None  # autoavaliação do próprio disco
    temperature: int | None = None
    power_on_hours: int | None = None
    reallocated: int = 0
    pending: int = 0
    uncorrectable: int = 0
    media_errors: int = 0  # NVMe
    percentage_used: int | None = None  # desgaste do NVMe/SSD
    rotational: bool = False
    model: str = ""
    serial: str = ""
    problems: list[str] = field(default_factory=list)  # códigos: failing, reallocated, pending…

    @property
    def level(self) -> str:
        """ok | warning | error | unknown"""
        if not self.available:
            return "unknown"
        if "failing" in self.problems or "uncorrectable" in self.problems or "media-errors" in self.problems:
            return "error"
        if self.problems:
            return "warning"
        return "ok"


def _raw(table: list[dict[str, Any]], attr_id: int) -> int:
    for attr in table:
        if attr.get("id") == attr_id:
            raw = attr.get("raw") or {}
            try:
                return int(raw.get("value", 0))
            except (TypeError, ValueError):
                return 0
    return 0


def parse_smartctl(device: str, text: str) -> SmartInfo:
    info = SmartInfo(device)
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return info
    if not isinstance(data, dict):
        return info
    status = data.get("smart_status")
    if not isinstance(status, dict) or "passed" not in status:
        return info  # sem SMART (USB sem passagem, cartão, VM…)
    info.available = True
    info.passed = bool(status.get("passed"))
    info.model = str(data.get("model_name") or "")
    info.serial = str(data.get("serial_number") or "")
    info.rotational = bool(data.get("rotation_rate"))
    temperature = (data.get("temperature") or {}).get("current")
    if isinstance(temperature, int):
        info.temperature = temperature
    hours = (data.get("power_on_time") or {}).get("hours")
    if isinstance(hours, int):
        info.power_on_hours = hours
    table = (data.get("ata_smart_attributes") or {}).get("table") or []
    info.reallocated = _raw(table, REALLOCATED)
    info.pending = _raw(table, PENDING)
    info.uncorrectable = _raw(table, UNCORRECTABLE)
    nvme = data.get("nvme_smart_health_information_log") or {}
    if nvme:
        info.media_errors = int(nvme.get("media_errors") or 0)
        used = nvme.get("percentage_used")
        if isinstance(used, int):
            info.percentage_used = used
        if info.temperature is None and isinstance(nvme.get("temperature"), int):
            info.temperature = nvme["temperature"]

    if info.passed is False:
        info.problems.append("failing")
    if info.uncorrectable:
        info.problems.append("uncorrectable")
    if info.media_errors:
        info.problems.append("media-errors")
    if info.reallocated:
        info.problems.append("reallocated")
    if info.pending:
        info.problems.append("pending")
    hot = HOT_HDD if info.rotational else HOT_SSD
    if info.temperature is not None and info.temperature >= hot:
        info.problems.append("hot")
    if info.percentage_used is not None and info.percentage_used >= 90:
        info.problems.append("worn")
    return info


def parse_health_results(results: dict[str, str]) -> dict[str, SmartInfo]:
    """Resultados do helper ``disk-health``: ``smart:<dispositivo>`` → JSON do smartctl (uma linha)."""
    return {
        key.removeprefix("smart:"): parse_smartctl(key.removeprefix("smart:"), value)
        for key, value in results.items()
        if key.startswith("smart:")
    }
