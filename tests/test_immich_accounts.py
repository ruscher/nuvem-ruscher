"""Contas e compartilhamento: as chamadas exatas da API do Immich v3.2.4 (sem rede)."""

import pytest

from nuvem_ruscher.core import immich_api
from nuvem_ruscher.core.immich_api import ImmichClient

ADMIN = "11111111-1111-4111-8111-111111111111"
MARIA = "22222222-2222-4222-8222-222222222222"
ALBUM = "33333333-3333-4333-8333-333333333333"


class Recorder(ImmichClient):
    def __init__(self, replies):
        super().__init__()
        self.calls = []
        self.replies = list(replies)

    def _request(self, method, path, body=None, token=None, api_key=None, query=None):
        self.calls.append((method, path, body, token, query))
        return self.replies.pop(0) if self.replies else None


def user_row(**kw):
    row = {
        "id": MARIA,
        "name": "Maria",
        "email": "maria@example.com",
        "isAdmin": False,
        "status": "active",
        "quotaSizeInBytes": 100 * 1024**3,
        "quotaUsageInBytes": 30 * 1024**3,
        "storageLabel": None,
        "shouldChangePassword": True,
        "deletedAt": None,
    }
    row.update(kw)
    return row


def test_session_keeps_only_what_is_needed():
    api = Recorder([{"accessToken": "tok", "userId": ADMIN, "name": "Ana", "userEmail": "a@x.com", "isAdmin": True}])
    s = api.session(" a@x.com ", "senha")
    assert (s.token, s.user_id, s.is_admin) == ("tok", ADMIN, True)
    assert api.calls[0][:3] == ("POST", "/auth/login", {"email": "a@x.com", "password": "senha"})


def test_create_user_forces_password_change_and_no_email():
    api = Recorder([user_row()])
    user = api.create_user("tok", " Maria ", "maria@example.com", "Temp-1234", 100 * 1024**3)
    method, path, body, token, _q = api.calls[0]
    assert (method, path, token) == ("POST", "/admin/users", "tok")
    assert body["shouldChangePassword"] is True
    assert body["notify"] is False
    assert body["quotaSizeInBytes"] == 100 * 1024**3
    assert body["name"] == "Maria"
    assert "storageLabel" not in body
    assert user.quota == 100 * 1024**3 and user.usage == 30 * 1024**3


def test_unlimited_quota_is_null():
    api = Recorder([user_row(quotaSizeInBytes=None)])
    assert api.create_user("tok", "Maria", "m@x.com", "x" * 10, None).quota is None
    assert api.calls[0][2]["quotaSizeInBytes"] is None


def test_list_users_with_deleted_and_status():
    api = Recorder([[user_row(), user_row(id=ADMIN, isAdmin=True), user_row(status="deleted", deletedAt="2026")]])
    users = api.admin_users("tok")
    assert api.calls[0][4] == {"withDeleted": "true"}
    assert [u.disabled for u in users] == [False, False, True]


def test_disable_is_soft_and_restore_exists():
    api = Recorder([user_row(status="deleted"), user_row()])
    api.disable_user("tok", MARIA)
    api.restore_user("tok", MARIA)
    assert api.calls[0][:3] == ("DELETE", f"/admin/users/{MARIA}", {"force": False})
    assert api.calls[1][:2] == ("POST", f"/admin/users/{MARIA}/restore")


def test_reset_password_generates_temporary_password():
    api = Recorder([user_row()])
    password = api.reset_password("tok", MARIA)
    assert len(password) == 16 and not set(password) & set("0O1lI")
    assert api.calls[0][2] == {"password": password, "shouldChangePassword": True}


def test_update_maps_fields():
    api = Recorder([user_row()])
    api.update_user("tok", MARIA, quota=None, storage_label="maria", name="Maria S.")
    assert api.calls[0][2] == {"quotaSizeInBytes": None, "storageLabel": "maria", "name": "Maria S."}


@pytest.mark.parametrize("bad", ["../admin", "x?y=1", "", "11111111-1111-4111-8111-11111111111/"])
def test_ids_are_validated_before_building_urls(bad):
    api = Recorder([])
    with pytest.raises(ValueError):
        api.disable_user("tok", bad)
    assert api.calls == []


def test_usage_by_user():
    api = Recorder([{"usageByUser": [{"userId": MARIA, "photos": 10, "videos": 2, "usage": 999}]}])
    assert api.usage_by_user("tok") == {MARIA: (10, 2, 999)}


def album_row():
    return {
        "id": ALBUM,
        "albumName": "Família",
        "assetCount": 42,
        "shared": True,
        "albumUsers": [
            {"role": "owner", "user": {"id": ADMIN, "name": "Ana", "email": "a@x.com"}},
            {"role": "editor", "user": {"id": MARIA, "name": "Maria", "email": "m@x.com"}},
        ],
    }


def test_shared_album_roundtrip():
    api = Recorder([album_row(), [album_row()], album_row(), None, None])
    album = api.create_album("tok", " Família ", [(MARIA, "editor")])
    assert api.calls[0][2] == {
        "albumName": "Família",
        "description": "",
        "albumUsers": [{"userId": MARIA, "role": "editor"}],
    }
    assert album.owner.name == "Ana" and [m.role for m in album.members] == ["editor"]
    api.albums("tok", owned=True, shared=True)
    assert api.calls[1][4] == {"isOwned": "true", "isShared": "true"}
    api.add_album_members("tok", ALBUM, [(MARIA, "viewer")])
    assert api.calls[2][:2] == ("PUT", f"/albums/{ALBUM}/users")
    api.set_album_role("tok", ALBUM, MARIA, "viewer")
    assert api.calls[3][:3] == ("PUT", f"/albums/{ALBUM}/user/{MARIA}", {"role": "viewer"})
    api.remove_album_member("tok", ALBUM, MARIA)
    assert api.calls[4][:2] == ("DELETE", f"/albums/{ALBUM}/user/{MARIA}")


def test_owner_role_cannot_be_granted():
    with pytest.raises(ValueError):
        Recorder([]).create_album("tok", "x", [(MARIA, "owner")])


def test_partners():
    api = Recorder([[{"id": MARIA, "name": "Maria", "email": "m@x.com"}], None, None])
    assert api.partners("tok", "shared-by")[0].name == "Maria"
    assert api.calls[0][4] == {"direction": "shared-by"}
    api.add_partner("tok", MARIA)
    assert api.calls[1][:3] == ("POST", "/partners", {"sharedWithId": MARIA})
    api.remove_partner("tok", MARIA)
    assert api.calls[2][:2] == ("DELETE", f"/partners/{MARIA}")
    with pytest.raises(ValueError):
        api.partners("tok", "everyone")


def test_over_quota():
    user = immich_api.user_from_api(user_row(quotaSizeInBytes=10, quotaUsageInBytes=10))
    assert user.over_quota
