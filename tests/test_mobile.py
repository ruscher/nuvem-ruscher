"""Android e iPhone: o que cada um mostra (core.mobile), sem GTK."""

import re

import pytest

from nuvem_ruscher import constants
from nuvem_ruscher.core import mobile
from nuvem_ruscher.core.mobile import ANDROID, IOS


def test_android_store_urls_are_unchanged():
    assert constants.PLAY_STORE_URL == "https://play.google.com/store/apps/details?id=app.alextran.immich"
    assert constants.FDROID_URL == "https://f-droid.org/packages/app.alextran.immich/"
    assert [s.url for s in ANDROID.stores] == [constants.PLAY_STORE_URL, constants.FDROID_URL]


def test_app_store_url_is_the_official_one():
    # Link da documentação do Immich (v3.2.4); só https, só apps.apple.com, id do app oficial.
    assert re.fullmatch(r"https://apps\.apple\.com/[a-z]{2}/app/immich/id1613945652", constants.APP_STORE_URL)
    assert [s.url for s in IOS.stores] == [constants.APP_STORE_URL]
    assert [s.name for s in IOS.stores] == ["App Store"]


def test_tailscale_store_follows_the_platform():
    assert IOS.tailscale.url.startswith("https://apps.apple.com/") and IOS.tailscale.url.endswith("/id1470499037")
    assert ANDROID.tailscale.url == "https://play.google.com/store/apps/details?id=com.tailscale.ipn"


def test_iphone_never_sees_android_stores_or_tips():
    urls = {s.url for s in IOS.stores}
    assert constants.PLAY_STORE_URL not in urls and constants.FDROID_URL not in urls
    text = " ".join(n.title + n.body + n.details for n in (*mobile.phone_steps(IOS), *mobile.good_to_know(IOS)))
    assert "Battery" not in text and "Unrestricted" not in text and "Android" not in text
    assert "Background App Refresh" in text


def test_android_never_sees_ios_tips():
    notes = (*mobile.phone_steps(ANDROID), *mobile.good_to_know(ANDROID), *mobile.troubleshooting(ANDROID))
    text = " ".join(n.title + n.body + n.details for n in notes)
    for ios_only in ("Background App Refresh", "iCloud", "iPhone", "Local Network", "App Store"):
        assert ios_only not in text
    assert "Unrestricted" in text


def test_steps_are_in_order_and_shared_where_they_should_be():
    for p in mobile.PLATFORMS:
        ids = [n.id for n in mobile.phone_steps(p)]
        assert ids[0] == "sign-in" and ids[-2:] == ["enable-backup", "background"]
        assert ids.index("photos") < ids.index("albums")
    assert "local-network" in [n.id for n in mobile.phone_steps(IOS)]
    assert "local-network" not in [n.id for n in mobile.phone_steps(ANDROID)]


def test_icloud_and_free_up_space_are_explained_carefully():
    notes = {n.id: n for n in IOS.good_to_know}
    assert notes["icloud"].details  # detalhes só sob demanda
    free = notes["free-up-space"]
    assert "also removes it from iCloud" in free.details and "Recently Deleted" in free.details


def test_away_mode_adds_tailscale_and_cellular_help():
    assert mobile.troubleshooting(IOS, away=True)[0].id == "tailscale"
    assert "tailscale" not in [n.id for n in mobile.troubleshooting(IOS, away=False)]
    assert mobile.good_to_know(ANDROID, away=True)[1].id == "cellular"


@pytest.mark.parametrize("value", ["", "windows-phone", None])
def test_unknown_platform_falls_back_to_android(value):
    assert mobile.platform(value or "") is ANDROID
    assert mobile.platform("ios") is IOS


def test_no_note_promises_continuous_background_on_ios():
    text = IOS.background.body.lower()
    assert "decides when" in text and "always" not in text and "continuous" not in text
