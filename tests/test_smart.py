"""SMART: do JSON do smartctl para um estado explicável."""

import json

from nuvem_ruscher.core import smart


def ata(passed=True, realloc=0, pending=0, uncorrectable=0, temp=34, rpm=7200):
    return json.dumps(
        {
            "model_name": "Exemplo HDD 4TB",
            "serial_number": "S-1",
            "rotation_rate": rpm,
            "smart_status": {"passed": passed},
            "temperature": {"current": temp},
            "power_on_time": {"hours": 12034},
            "ata_smart_attributes": {
                "table": [
                    {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": realloc}},
                    {"id": 197, "name": "Current_Pending_Sector", "raw": {"value": pending}},
                    {"id": 198, "name": "Offline_Uncorrectable", "raw": {"value": uncorrectable}},
                ]
            },
        }
    )


def test_healthy_hdd():
    info = smart.parse_smartctl("/dev/sdb", ata())
    assert info.available and info.passed
    assert (info.temperature, info.power_on_hours, info.rotational) == (34, 12034, True)
    assert info.level == "ok"


def test_reallocated_and_pending_are_warnings():
    info = smart.parse_smartctl("/dev/sdb", ata(realloc=8, pending=2))
    assert info.problems == ["reallocated", "pending"]
    assert info.level == "warning"


def test_failing_or_uncorrectable_are_errors():
    assert smart.parse_smartctl("/dev/sdb", ata(passed=False)).level == "error"
    assert smart.parse_smartctl("/dev/sdb", ata(uncorrectable=1)).level == "error"


def test_hot_hdd_but_cool_ssd():
    assert "hot" in smart.parse_smartctl("/dev/sdb", ata(temp=58)).problems
    assert "hot" not in smart.parse_smartctl("/dev/sdb", ata(temp=58, rpm=0)).problems


def test_nvme():
    data = {
        "model_name": "Exemplo NVMe",
        "smart_status": {"passed": True},
        "nvme_smart_health_information_log": {"temperature": 41, "percentage_used": 3, "media_errors": 0},
    }
    info = smart.parse_smartctl("/dev/nvme0n1", json.dumps(data))
    assert (info.temperature, info.percentage_used, info.level) == (41, 3, "ok")
    data["nvme_smart_health_information_log"]["media_errors"] = 4
    assert smart.parse_smartctl("/dev/nvme0n1", json.dumps(data)).level == "error"
    data["nvme_smart_health_information_log"].update(media_errors=0, percentage_used=95)
    assert smart.parse_smartctl("/dev/nvme0n1", json.dumps(data)).problems == ["worn"]


def test_no_smart_support_is_unknown_not_error():
    for text in ("", "não é json", json.dumps({"device": {"name": "/dev/sdx"}}), "[]"):
        assert smart.parse_smartctl("/dev/sdx", text).level == "unknown"


def test_helper_results():
    results = {"smart:/dev/sdb": ata(), "smart:/dev/sdc": ata(realloc=1), "mountpoint": "/x"}
    parsed = smart.parse_health_results(results)
    assert set(parsed) == {"/dev/sdb", "/dev/sdc"}
    assert parsed["/dev/sdc"].level == "warning"
