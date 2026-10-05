"""Cliente mínimo da API do Immich (urllib, sem dependências).

Endpoints conferidos na OpenAPI da v3.2.4 (docs/01-pesquisa-immich.md).
"""

from __future__ import annotations

import http.client
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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
        query: dict[str, str] | None = None,
    ) -> Any:
        if query:
            path = f"{path}?{urllib.parse.urlencode(query)}"
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
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as exc:
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

    # --- sessão e contas (doc 10; OpenAPI v3.2.4) ------------------------------------------
    def session(self, email: str, password: str) -> Session:
        r = self._request("POST", "/auth/login", {"email": email.strip(), "password": password})
        return Session(
            token=str(r["accessToken"]),
            user_id=str(r.get("userId", "")),
            name=str(r.get("name", "")),
            email=str(r.get("userEmail", email.strip())),
            is_admin=bool(r.get("isAdmin")),
        )

    def admin_users(self, token: str) -> list[ImmichUser]:
        rows = self._request("GET", "/admin/users", token=token, query={"withDeleted": "true"}) or []
        return [user_from_api(row) for row in rows]

    def usage_by_user(self, token: str) -> dict[str, tuple[int, int, int]]:
        """userId → (fotos, vídeos, bytes)."""
        s = self._request("GET", "/server/statistics", token=token) or {}
        rows = s.get("usageByUser") if isinstance(s, dict) else None
        return {
            str(u["userId"]): (int(u.get("photos") or 0), int(u.get("videos") or 0), int(u.get("usage") or 0))
            for u in rows or []
            if isinstance(u, dict) and u.get("userId")
        }

    def create_user(
        self,
        token: str,
        name: str,
        email: str,
        password: str,
        quota: int | None,
        storage_label: str | None = None,
        is_admin: bool = False,
    ) -> ImmichUser:
        body: dict[str, Any] = {
            "name": name.strip(),
            "email": email.strip(),
            "password": password,
            "shouldChangePassword": True,
            "quotaSizeInBytes": quota,
            "isAdmin": is_admin,
            "notify": False,
        }
        if storage_label:
            body["storageLabel"] = storage_label
        return user_from_api(self._request("POST", "/admin/users", body, token=token))

    def update_user(self, token: str, user_id: str, **changes: Any) -> ImmichUser:
        allowed = {
            "name": "name",
            "email": "email",
            "quota": "quotaSizeInBytes",
            "storage_label": "storageLabel",
            "is_admin": "isAdmin",
            "password": "password",
            "should_change_password": "shouldChangePassword",
        }
        body = {allowed[key]: value for key, value in changes.items() if key in allowed}
        return user_from_api(self._request("PUT", f"/admin/users/{_id(user_id)}", body, token=token))

    def reset_password(self, token: str, user_id: str) -> str:
        """Senha temporária: o Immich pede a troca no próximo acesso (como a interface web)."""
        password = generate_password()
        self.update_user(token, user_id, password=password, should_change_password=True)
        return password

    def disable_user(self, token: str, user_id: str) -> ImmichUser:
        """Exclusão comum (sem force): a conta para de entrar e pode ser reativada no prazo."""
        return user_from_api(self._request("DELETE", f"/admin/users/{_id(user_id)}", {"force": False}, token=token))

    def restore_user(self, token: str, user_id: str) -> ImmichUser:
        return user_from_api(self._request("POST", f"/admin/users/{_id(user_id)}/restore", token=token))

    def people(self, token: str) -> list[Person]:
        rows = self._request("GET", "/users", token=token) or []
        return [Person(str(r["id"]), str(r.get("name", "")), str(r.get("email", ""))) for r in rows]

    # --- compartilhamento (doc 11) -------------------------------------------------------------
    def albums(self, token: str, owned: bool | None = None, shared: bool | None = None) -> list[Album]:
        query = {}
        if owned is not None:
            query["isOwned"] = "true" if owned else "false"
        if shared is not None:
            query["isShared"] = "true" if shared else "false"
        rows = self._request("GET", "/albums", token=token, query=query) or []
        return [album_from_api(row) for row in rows]

    def create_album(self, token: str, name: str, members: list[tuple[str, str]], description: str = "") -> Album:
        body = {
            "albumName": name.strip(),
            "description": description,
            "albumUsers": [{"userId": _id(uid), "role": _role(role)} for uid, role in members],
        }
        return album_from_api(self._request("POST", "/albums", body, token=token))

    def add_album_members(self, token: str, album_id: str, members: list[tuple[str, str]]) -> Album:
        body = {"albumUsers": [{"userId": _id(uid), "role": _role(role)} for uid, role in members]}
        return album_from_api(self._request("PUT", f"/albums/{_id(album_id)}/users", body, token=token))

    def set_album_role(self, token: str, album_id: str, user_id: str, role: str) -> None:
        self._request("PUT", f"/albums/{_id(album_id)}/user/{_id(user_id)}", {"role": _role(role)}, token=token)

    def remove_album_member(self, token: str, album_id: str, user_id: str) -> None:
        self._request("DELETE", f"/albums/{_id(album_id)}/user/{_id(user_id)}", token=token)

    def partners(self, token: str, direction: str) -> list[Person]:
        if direction not in ("shared-by", "shared-with"):
            raise ValueError(direction)
        rows = self._request("GET", "/partners", token=token, query={"direction": direction}) or []
        return [Person(str(r["id"]), str(r.get("name", "")), str(r.get("email", ""))) for r in rows]

    def add_partner(self, token: str, user_id: str) -> None:
        self._request("POST", "/partners", {"sharedWithId": _id(user_id)}, token=token)

    def remove_partner(self, token: str, user_id: str) -> None:
        self._request("DELETE", f"/partners/{_id(user_id)}", token=token)


# --- modelos -------------------------------------------------------------------------------

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ROLES = ("editor", "viewer")
# Sem 0/O, 1/l/I: a senha temporária é lida em voz alta ou copiada de uma tela.
UNAMBIGUOUS_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def _id(value: str) -> str:
    """IDs vão para a URL: só UUIDs de verdade (nada de "../" ou "?")."""
    if not UUID_RE.match(value or ""):
        raise ValueError(f"invalid id: {value!r}")
    return value


def _role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"invalid role: {role!r}")
    return role


def generate_password(length: int = 16) -> str:
    return "".join(secrets.choice(UNAMBIGUOUS_CHARS) for _ in range(length))


@dataclass(frozen=True)
class Session:
    """Sessão de um usuário do Immich. Só na memória; ``logout`` ao sair."""

    token: str
    user_id: str
    name: str
    email: str
    is_admin: bool


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    email: str


@dataclass
class ImmichUser:
    id: str
    name: str
    email: str
    is_admin: bool = False
    status: str = "active"  # active | removing | deleted
    quota: int | None = None  # None = ilimitado
    usage: int | None = None  # o que conta para a quota
    storage_label: str | None = None
    should_change_password: bool = False
    deleted_at: str | None = None
    photos: int = 0
    videos: int = 0

    @property
    def disabled(self) -> bool:
        return self.status in ("deleted", "removing") or bool(self.deleted_at)

    @property
    def over_quota(self) -> bool:
        return self.quota is not None and self.usage is not None and self.usage >= self.quota


def user_from_api(row: dict[str, Any]) -> ImmichUser:
    return ImmichUser(
        id=str(row["id"]),
        name=str(row.get("name", "")),
        email=str(row.get("email", "")),
        is_admin=bool(row.get("isAdmin")),
        status=str(row.get("status") or "active"),
        quota=row.get("quotaSizeInBytes"),
        usage=row.get("quotaUsageInBytes"),
        storage_label=row.get("storageLabel"),
        should_change_password=bool(row.get("shouldChangePassword")),
        deleted_at=row.get("deletedAt"),
    )


@dataclass(frozen=True)
class AlbumMember:
    user_id: str
    name: str
    email: str
    role: str  # owner | editor | viewer


@dataclass
class Album:
    id: str
    name: str
    description: str = ""
    asset_count: int = 0
    shared: bool = False
    owner: AlbumMember | None = None
    members: list[AlbumMember] = field(default_factory=list)  # sem o dono
    updated_at: str = ""


def album_from_api(row: dict[str, Any]) -> Album:
    people = [
        AlbumMember(
            str((entry.get("user") or {}).get("id", "")),
            str((entry.get("user") or {}).get("name", "")),
            str((entry.get("user") or {}).get("email", "")),
            str(entry.get("role", "viewer")),
        )
        for entry in row.get("albumUsers") or []
    ]
    owner = next((p for p in people if p.role == "owner"), None)
    return Album(
        id=str(row["id"]),
        name=str(row.get("albumName", "")),
        description=str(row.get("description") or ""),
        asset_count=int(row.get("assetCount") or 0),
        shared=bool(row.get("shared")),
        owner=owner,
        members=[p for p in people if p is not owner],
        updated_at=str(row.get("updatedAt") or ""),
    )


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read() or b"{}")
    except (ValueError, OSError, http.client.HTTPException):
        return exc.reason or str(exc.code)
    if not isinstance(payload, dict):
        return str(exc.reason or exc.code)
    message = payload.get("message")
    if isinstance(message, list):
        return "; ".join(str(m) for m in message)
    return str(message or exc.reason or exc.code)
