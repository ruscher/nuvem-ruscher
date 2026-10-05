"""Cliente mínimo da API do Immich (urllib, sem dependências).

Endpoints conferidos na OpenAPI da v3.2.4 (docs/01-pesquisa-immich.md).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from nuvem_ruscher.constants import API_KEY_PERMISSIONS

# Serviços do hwaccel.transcoding.yml → enum TranscodeHWAccel da API (v3.2.4).
TRANSCODE_TO_ACCEL = {"vaapi": "vaapi", "quicksync": "qsv", "nvenc": "nvenc"}


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ServerStats:
    photos: int
    videos: int
    usage: int


class ImmichClient:
    def __init__(self, base_url: str = "http://127.0.0.1:2283", timeout: float = 8) -> None:
        self.base = base_url.rstrip("/") + "/api"
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        api_key: str | None = None,
    ) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json", "User-Agent": "nuvem-ruscher"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if api_key:
            headers["x-api-key"] = api_key
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, _error_message(exc)) from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ApiError(0, str(getattr(exc, "reason", exc))) from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise ApiError(0, "invalid server response") from None

    def ping(self) -> bool:
        try:
            return (self._request("GET", "/server/ping") or {}).get("res") == "pong"
        except ApiError:
            return False

    def version(self) -> str:
        v = self._request("GET", "/server/version")
        return f"v{v['major']}.{v['minor']}.{v['patch']}"

    def config(self) -> dict[str, Any]:
        return dict(self._request("GET", "/server/config") or {})

    def is_initialized(self) -> bool:
        return bool(self.config().get("isInitialized"))

    def admin_sign_up(self, name: str, email: str, password: str) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/auth/admin-sign-up",
                {"name": name, "email": email.strip(), "password": password},
            )
        )

    def login(self, email: str, password: str) -> str:
        result = self._request("POST", "/auth/login", {"email": email.strip(), "password": password})
        return str(result["accessToken"])

    def logout(self, token: str) -> None:
        try:
            self._request("POST", "/auth/logout", token=token)
        except ApiError:
            pass

    def create_stats_key(self, token: str, name: str = "Nuvem Ruscher (painel)") -> str:
        result = self._request(
            "POST",
            "/api-keys",
            {"name": name, "permissions": list(API_KEY_PERMISSIONS)},
            token=token,
        )
        return str(result["secret"])

    def apply_initial_settings(self, token: str, transcode: str, ml_enabled: bool) -> None:
        """Liga a transcodificação por hardware escolhida e, se pedido, desliga o ML.

        O override só expõe a GPU ao container; o Immich também precisa ser avisado.
        """
        accel = TRANSCODE_TO_ACCEL.get(transcode)
        if accel is None and ml_enabled:
            return
        config = dict(self._request("GET", "/system-config", token=token) or {})
        if accel is not None:
            config.setdefault("ffmpeg", {})["accel"] = accel
        if not ml_enabled:
            config.setdefault("machineLearning", {})["enabled"] = False
        self._request("PUT", "/system-config", config, token=token)

    def statistics(self, api_key: str) -> ServerStats:
        s = self._request("GET", "/server/statistics", api_key=api_key)
        return ServerStats(int(s.get("photos", 0)), int(s.get("videos", 0)), int(s.get("usage", 0)))


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read() or b"{}")
    except ValueError:
        return exc.reason or str(exc.code)
    message = payload.get("message")
    if isinstance(message, list):
        return "; ".join(str(m) for m in message)
    return str(message or exc.reason or exc.code)
