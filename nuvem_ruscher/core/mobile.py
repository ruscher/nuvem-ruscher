"""Celulares: o que muda entre Android e iPhone, num lugar só.

A interface lê estas descrições; não há ``if iphone`` espalhado pelas telas. Os textos
seguem o app oficial do Immich (v3.2.4) e a documentação dele — veja
docs/ios-support-audit.md para as fontes de cada afirmação.
"""

from __future__ import annotations

from dataclasses import dataclass

from nuvem_ruscher.constants import (
    APP_STORE_URL,
    FDROID_URL,
    PLAY_STORE_URL,
    TAILSCALE_APP_STORE_URL,
    TAILSCALE_PLAY_STORE_URL,
)
from nuvem_ruscher.i18n import N_


@dataclass(frozen=True)
class Store:
    name: str  # marca, não se traduz
    url: str


@dataclass(frozen=True)
class Note:
    """Um passo ou dica: título, texto curto e, se houver, detalhes (mostrados sob demanda)."""

    id: str
    icon: str
    title: str
    body: str
    details: str = ""


@dataclass(frozen=True)
class MobilePlatform:
    id: str
    label: str
    stores: tuple[Store, ...]  # a primeira vira o QR
    tailscale: Store
    photos: Note  # permissão de acesso às fotos
    albums: Note  # o que escolher para o backup
    background: Note  # continuar o backup em segundo plano
    permissions: tuple[Note, ...] = ()  # outras permissões que o Immich pede neste sistema
    good_to_know: tuple[Note, ...] = ()
    trouble: tuple[Note, ...] = ()  # causas a mais quando o celular não conecta


ANDROID = MobilePlatform(
    id="android",
    label=N_("Android"),
    stores=(Store("Play Store", PLAY_STORE_URL), Store("F-Droid", FDROID_URL)),
    tailscale=Store("Play Store", TAILSCALE_PLAY_STORE_URL),
    photos=Note(
        "photos",
        "image-x-generic-symbolic",
        N_("Allow access to all photos"),
        N_("When Immich asks, allow access to all photos and videos. If you pick only some, the others are not saved."),
    ),
    albums=Note(
        "albums",
        "camera-photo-symbolic",
        N_("Choose what to protect"),
        N_(
            "Tap the cloud icon at the top, then “Select”, and choose “Camera” (and any other folder you want, "
            "such as WhatsApp Images)."
        ),
    ),
    background=Note(
        "background",
        "battery-symbolic",
        N_("Take Immich out of battery saving"),
        N_(
            "Settings → Apps → Immich → Battery → “Unrestricted”. Otherwise Android may stop the backup "
            "when the screen is off."
        ),
    ),
    good_to_know=(
        Note(
            "free-up-space",
            "user-trash-symbolic",
            N_("Need more space on the phone?"),
            N_("After the backup, Immich’s “Free Up Space” removes from the phone the photos already in your cloud."),
            N_(
                "Immich shows the list before removing anything, can keep favorites and albums, and sends the "
                "photos to the phone’s trash first. Open a few of them in your cloud before emptying the trash. "
                "If another service (such as Google Photos) syncs this phone, removing here may remove there too."
            ),
        ),
    ),
)

IOS = MobilePlatform(
    id="ios",
    label=N_("iPhone or iPad"),
    stores=(Store("App Store", APP_STORE_URL),),
    tailscale=Store("App Store", TAILSCALE_APP_STORE_URL),
    photos=Note(
        "photos",
        "image-x-generic-symbolic",
        N_("Allow access to all photos"),
        N_(
            "When Immich asks, allow full access. With “Limited Access”, iOS only shows Immich the photos "
            "you picked, and the others are not saved."
        ),
    ),
    albums=Note(
        "albums",
        "camera-photo-symbolic",
        N_("Choose what to protect"),
        N_("Tap the cloud icon at the top, then “Select”, and choose “Recents”: it has every photo on the iPhone."),
    ),
    background=Note(
        "background",
        "view-refresh-symbolic",
        N_("Let iOS continue the backup"),
        N_(
            "Settings → General → Background App Refresh → turn on Immich. The iPhone decides when the "
            "backup runs in the background; opening Immich now and then helps it keep up."
        ),
    ),
    permissions=(
        Note(
            "local-network",
            "network-wireless-symbolic",
            N_("Allow “Local Network”"),
            N_(
                "When Immich asks to find devices on your local network, tap “Allow”: that is how it reaches "
                "your cloud at home."
            ),
        ),
    ),
    good_to_know=(
        Note(
            "icloud",
            "weather-overcast-symbolic",
            N_("Photos in iCloud"),
            N_(
                "With iCloud Photos and “Optimize iPhone Storage”, Immich first downloads each original from "
                "iCloud, then saves it in your cloud."
            ),
            N_(
                "This uses internet data and some temporary space on the iPhone, which Immich frees after each "
                "photo. For a large library, do the first backup on Wi-Fi with the iPhone charging. Nothing "
                "changes in iCloud."
            ),
        ),
        Note(
            "free-up-space",
            "user-trash-symbolic",
            N_("Need more space on the iPhone?"),
            N_("After the backup, Immich’s “Free Up Space” removes from the iPhone the photos already in your cloud."),
            N_(
                "If you use iCloud Photos, read this first: removing a photo from the iPhone also removes it "
                "from iCloud. Afterwards it exists only in your cloud (and in “Recently Deleted” for 30 days). "
                "If iCloud is your backup, use “Optimize iPhone Storage” instead. Immich shows the list before "
                "removing anything and can keep favorites and albums."
            ),
        ),
    ),
    trouble=(
        Note(
            "local-network",
            "network-wireless-symbolic",
            N_("Local Network permission"),
            N_(
                "If the page opens in the browser but not in Immich: Settings → Privacy & Security → "
                "Local Network → turn on Immich."
            ),
        ),
    ),
)

PLATFORMS: tuple[MobilePlatform, ...] = (ANDROID, IOS)

# Iguais nos dois sistemas.
SIGN_IN = Note(
    "sign-in",
    "avatar-default-symbolic",
    N_("Sign in with your own account"),
    N_(
        "Each person uses the email and password of their own account (created in Accounts). Do not share "
        "an account: each one keeps its own photos."
    ),
)
ENABLE_BACKUP = Note(
    "enable-backup",
    "nr-status-ok-symbolic",
    N_("Turn on “Enable Backup”"),
    N_("From then on, new photos are saved by themselves. By default, only on Wi-Fi."),
)
FIRST_BACKUP = Note(
    "first-backup",
    "document-save-symbolic",
    N_("The first backup takes time"),
    N_("Thousands of photos can take hours. Leave the phone on Wi-Fi and charging, with Immich open."),
    N_("Photos and videos are saved as they are, Live Photos included: nothing is compressed or converted."),
)
CELLULAR = Note(
    "cellular",
    "network-cellular-symbolic",
    N_("Backup on mobile data"),
    N_("Immich saves only on Wi-Fi unless you turn on “Use cellular data” in its backup settings."),
)
TROUBLE = (
    Note(
        "same-wifi",
        "network-wireless-symbolic",
        N_("Same Wi-Fi"),
        N_(
            "The phone must be on the same Wi-Fi as this computer. Guest networks usually keep devices apart: "
            "use the main one."
        ),
    ),
    Note(
        "vpn",
        "network-vpn-symbolic",
        N_("VPN on the phone"),
        N_("A VPN app on the phone can hide your home network. Turn it off and try again."),
    ),
    Note(
        "rescan",
        "view-refresh-symbolic",
        N_("Address changed"),
        N_("After restarting the router, the address may change. Check the address above and type it again."),
    ),
)
TROUBLE_AWAY = Note(
    "tailscale",
    "network-vpn-symbolic",
    N_("Tailscale on the phone"),
    N_("Away from home, Tailscale must be on in the phone, signed in to the same account as this computer."),
)


def platform(platform_id: str) -> MobilePlatform:
    """A plataforma pelo id; qualquer outro valor (estado antigo, typo) vira Android."""
    return next((p for p in PLATFORMS if p.id == platform_id), ANDROID)


def phone_steps(p: MobilePlatform) -> tuple[Note, ...]:
    """O que fazer no app depois de instalar e digitar o endereço, em ordem."""
    return (SIGN_IN, p.photos, *p.permissions, p.albums, ENABLE_BACKUP, p.background)


def good_to_know(p: MobilePlatform, away: bool = False) -> tuple[Note, ...]:
    return (FIRST_BACKUP, *((CELLULAR,) if away else ()), *p.good_to_know, *(() if away else (CELLULAR,)))


def troubleshooting(p: MobilePlatform, away: bool = False) -> tuple[Note, ...]:
    base = (TROUBLE_AWAY, *TROUBLE[1:]) if away else TROUBLE
    return (*base, *p.trouble)
