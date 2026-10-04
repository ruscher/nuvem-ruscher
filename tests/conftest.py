import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PHOTO_PATH = "/run/media/ruscher/Novo volume/immich-ruscher"
MOUNTPOINT = "/run/media/ruscher/Novo volume"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
