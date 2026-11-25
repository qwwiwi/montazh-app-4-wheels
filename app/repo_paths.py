"""Locations of the repository resources used by the modules in app/."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OFFICIAL_MEDIA = REPO / "assets" / "official-media"
