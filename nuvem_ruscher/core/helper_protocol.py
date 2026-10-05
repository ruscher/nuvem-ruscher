"""Protocolo de linhas do helper e tradução de erros para linguagem humana."""

from __future__ import annotations

from dataclasses import dataclass

from nuvem_ruscher.i18n import N_, _


@dataclass(frozen=True)
class HelperEvent:
    kind: str  # step, info, progress, result, error, log
    key: str = ""
    value: str = ""


def parse_line(line: str) -> HelperEvent:
    line = line.rstrip("\n")
    if not line.startswith("@@"):
        return HelperEvent("log", value=line)
    tag, _sep, rest = line[2:].partition(" ")
    tag = tag.lower()
    if tag == "result":
        key, _eq, value = rest.partition("=")
        return HelperEvent("result", key, value)
    if tag == "error":
        code, _sp, message = rest.partition(" ")
        return HelperEvent("error", code, message)
    if tag in ("step", "info", "progress"):
        return HelperEvent(tag, value=rest)
    return HelperEvent("log", value=line)


# código → (título, o que fazer)
ERRORS: dict[str, tuple[str, str]] = {
    "auth-cancelled": (
        N_("Authorization was canceled"),
        N_("Nothing was changed. Try again and type the administrator password when asked."),
    ),
    "not-authorized": (
        N_("Your user does not have administrator permission"),
        N_("Ask someone with administrator access to open Nuvem Ruscher and do this step."),
    ),
    "helper-missing": (
        N_("Nuvem Ruscher is not fully installed"),
        N_("Install the nuvem-ruscher package (or run “sudo make install”) and open the app again."),
    ),
    "invalid-argument": (
        N_("Some data sent did not pass the security check"),
        N_("Nothing was changed. Check the chosen folder and try again."),
    ),
    "storage-missing": (
        N_("The photo disk is not connected"),
        N_("Connect the disk, wait for it to appear in the file manager and try again."),
    ),
    "storage-unsafe": (
        N_("The photo folder is not in a safe place"),
        N_("Choose a folder inside a mounted disk. Nothing was changed."),
    ),
    "download-failed": (
        N_("Could not download the Immich files"),
        N_("Check the internet connection and try again. The process resumes where it stopped."),
    ),
    "pacman-failed": (
        N_("Package installation failed"),
        N_("Update the system through the software store (or “sudo pacman -Syu”) and try again."),
    ),
    "fstab-exists": (
        N_("This disk already has a mount rule"),
        N_("It is already configured in the system. No changes were made."),
    ),
    "fstab-invalid": (
        N_("The mount rule did not pass the check"),
        N_("Nothing was changed: the original file was restored automatically."),
    ),
    "unsupported-fs": (
        N_("This type of disk cannot be mounted automatically"),
        N_("The server still works, but only after you log in and open the disk."),
    ),
    "db-password-missing": (
        N_("There is an old database without its matching password"),
        N_("To avoid losing anything, the installation stopped. See the technical details to recover."),
    ),
    "service-failed": (
        N_("The server could not start"),
        N_("Check that the photo disk is connected and see the logs for more details."),
    ),
    "not-installed": (
        N_("The server has not been installed yet"),
        N_("Run the setup assistant first."),
    ),
    "not-running": (
        N_("The server is turned off"),
        N_("Turn on the server and try again."),
    ),
    "backup-failed": (
        N_("The database backup failed"),
        N_("Check the free space on the photo disk and try again."),
    ),
    "update-rolled-back": (
        N_("The update did not work, but everything is back as it was"),
        N_("Your server is still on the previous version, with all its data. See the technical details."),
    ),
    "rollback-failed": (
        N_("The update failed and so did the automatic rollback"),
        N_("Your photos are safe on the disk. See the technical details: a copy of the database was kept."),
    ),
    "no-space": (
        N_("Not enough space on the system disk"),
        N_("Free up space and try again."),
    ),
    "firewall-failed": (
        N_("Could not adjust the firewall"),
        N_("You can open port 2283 manually in the firewall settings."),
    ),
    "busy": (
        N_("Another task is already running"),
        N_("Wait for it to finish and try again. Nothing was changed."),
    ),
    "migration-cancelled": (
        N_("The move was canceled"),
        N_("Your photos stay where they were and the server keeps using them. You can resume later."),
    ),
    "migration-rolled-back": (
        N_("The move did not work, but everything is back as it was"),
        N_("The server is using the original folder again, with all your photos. The new copy was kept for checking."),
    ),
    "copy-failed": (
        N_("The photos could not be copied"),
        N_("The original folder was not touched. Check that the new disk is connected and has space, then try again."),
    ),
    "verify-failed": (
        N_("The copy did not match the original"),
        N_("To be safe, nothing was switched: the server keeps using the original folder. Check the new disk."),
    ),
    "dest-not-empty": (
        N_("The new folder already has files"),
        N_("Choose an empty folder, or a folder that already has a copy of the library."),
    ),
    "adopt-incomplete": (
        N_("The new folder does not have a complete library"),
        N_("Some Immich folders or files are missing there. Nothing was changed. Use “Move existing data” instead."),
    ),
    "old-copy-differs": (
        N_("The old copy has files that are not in the new location"),
        N_(
            "To be safe, the old copy was kept. They may be photos deleted later in Immich; "
            "you can remove the old folder yourself."
        ),
    ),
    "disk-protected": (
        N_("This drive cannot be used"),
        N_("It holds the system, your photos, the database, Docker or swap. Nothing was changed."),
    ),
    "disk-in-use": (
        N_("This drive is currently in use"),
        N_("It is mounted or used by another service (RAID, LVM, encryption). Nothing was changed."),
    ),
    "not-confirmed": (
        N_("The drives to erase were not confirmed"),
        N_("Nothing was erased. Start again and confirm each drive."),
    ),
    "raid-exists": (
        N_("There is already a Nuvem Ruscher array"),
        N_("Only one array is managed by the app. Nothing was changed."),
    ),
    "raid-failed": (
        N_("The array could not be created"),
        N_(
            "The drives you confirmed may already be erased, but your photos were not touched. "
            "See the technical details."
        ),
    ),
    "tool-missing": (
        N_("A required program is missing"),
        N_("Install it from the software store (or use the “Install” button) and try again."),
    ),
    "api-unavailable": (
        N_("Immich did not answer"),
        N_("Make sure the server is on and try again in a few seconds."),
    ),
    "internal": (
        N_("Something unexpected happened"),
        N_("Nothing in your photos was changed. See the technical details and try again."),
    ),
}


def human_error(code: str) -> tuple[str, str]:
    title, hint = ERRORS.get(code, ERRORS["internal"])
    return _(title), _(hint)


def pkexec_error_code(returncode: int) -> str | None:
    """pkexec devolve 126 quando o diálogo é fechado e 127 quando não autorizado."""
    if returncode == 126:
        return "auth-cancelled"
    if returncode == 127:
        return "not-authorized"
    return None
