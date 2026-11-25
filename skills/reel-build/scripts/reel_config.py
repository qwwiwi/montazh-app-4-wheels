"""Per-take configuration: head measurement and style constants.

The head is measured on the actual take (``measure_head.py`` + a look at the grid frame); it is never copied from another
reel. Everything else has the canon default: one visual system with our palette (dark + orange accent, one signal colour).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from pathlib import Path, PureWindowsPath
from typing import Any

import geometry as geo
from reel_captions import CaptionStyle


@dataclass(frozen=True)
class Colours:
    """Palette: three backgrounds (light with a grid, dark, one colour), one accent, one signal colour."""

    accent: str = "#D97757"      # orange: our accent, the one-colour background
    accent_on_light: str = "#B8431D"   # the accent as text on light backgrounds and cards: 5.4:1 (the plain accent gives 3.1:1)
    signal_on_light: str = "#2F7F4F"   # the signal green as text on light cards: 4.8:1 (the plain signal gives 3.0:1)
    signal: str = "#3FA66B"      # green: ticks, success
    ink: str = "#14110F"         # borders, hard shadows, text on light
    paper: str = "#F3EEE6"       # light background
    grid: str = "rgba(20,17,15,.075)"
    dark: str = "#0E0D0C"        # dark background
    dark_card: str = "#1C1916"
    card: str = "#FFFDF9"        # card on light and on the accent background
    muted: str = "#8A817A"       # switches that are off, skeleton rows: never text
    dim_on_light: str = "#5C544D"      # secondary text on light cards: 7:1 (the old muted grey gave 3.7:1)
    dim_on_dark: str = "#C9C0B6"       # secondary text on dark cards (terminal output): 10:1
    cream: str = "#F4EFE9"       # text on dark
    plate: str = "rgba(14,13,12,.88)"   # plate under a caption word over the speaker


@dataclass(frozen=True)
class FitStyle:
    """Caption type metrics (pixels of the 1080x1920 frame)."""

    font_px: int = 60
    pad_x: int = 18
    pad_y: int = 6
    radius: int = 14
    line_gap: int = 8
    word_gap: int = 12


HANDLE_RE = re.compile(r"[A-Za-z0-9._]{1,30}")
AVATAR_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


@dataclass(frozen=True)
class Account:
    """The owner's account as shown on the follow card: handle, optional display name, optional avatar file (absolute path).

    Nothing else is allowed on purpose: follower and post counters are never shown (they would be invented or go stale).
    """

    handle: str
    display_name: str = ""
    avatar: Path | None = None


@dataclass(frozen=True)
class ReelConfig:
    """Everything a build needs besides the words and the plan."""

    head: geo.Head
    split_air: int = 12         # source pixels kept above the hair in the split's speaker half
    colours: Colours = field(default_factory=Colours)
    fit: FitStyle = field(default_factory=FitStyle)
    captions: CaptionStyle = field(default_factory=CaptionStyle)
    face_pad: int = 10          # pixels added around the detected face box for the hard rule
    face_margin: float = 0.0    # extra clear space demanded by the gate between caption and face
    track_smooth: int = 2       # median radius (samples) applied to the face track
    account: Account | None = None   # owner's account for the follow card; None = the reel has no follow card
    assets_dir: Path | None = None   # folder with the files the owner supplied for this reel (logos); None = no such folder
    ui_kit: Path | None = None       # component library (qwwiwi/html-components) whose components, tokens and fonts the hc_* scenes use

    brand_mentions: Path | None = None  # manifest produced for this frozen cut

    @property
    def layout(self) -> geo.SplitLayout:
        """Speaker half of the split."""
        return geo.SplitLayout(geo.split_y0(self.head, self.split_air))


def _sub(cls: type, raw: dict[str, Any] | None) -> Any:
    raw = raw or {}
    names = {f.name for f in fields(cls)}
    unknown = set(raw) - names
    if unknown:
        raise ValueError(f"unknown config keys for {cls.__name__}: {sorted(unknown)}")
    return cls(**raw)


def local_file(name: str, base: Path, suffixes: tuple[str, ...], what: str) -> Path:
    """Resolve a file the owner supplied (relative to ``base``); refuse URLs, missing files and unexpected types.

    Raises:
        ValueError: when ``name`` is a URL, leaves ``base`` (absolute path, ``..``, a link out), does not exist, or has a suffix outside ``suffixes``.
    """
    if re.match(r"^[a-z][a-z0-9+.-]*:|^//", name, flags=re.I):
        raise ValueError(f"{what} {name!r} must be a local file of the owner, not a URL (nothing is downloaded)")
    # The documented contract (SKILL.md): a relative path without parent steps, whatever the resolved target is.
    if name.startswith(("/", "\\")) or PureWindowsPath(name).is_absolute() or ".." in re.split(r"[\\/]", name):
        raise ValueError(f"{what} {name!r} must be a relative path inside {base}: no absolute path and no parent step")
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"{what} {name!r} must stay inside {base} (no absolute path, parent step or link out of the folder)")
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"{what} {name!r}: file type must be one of {', '.join(suffixes)}")
    if not path.is_file():
        raise ValueError(f"{what} {path} does not exist")
    return path


def _account(raw: dict[str, Any] | None, base: Path) -> Account | None:
    """Parse the ``account`` block; the handle is stored without ``@``."""
    if raw is None:
        return None
    unknown = set(raw) - {"handle", "display_name", "avatar"}
    if unknown:
        raise ValueError(f"unknown account keys: {sorted(unknown)} (only handle, display_name, avatar are shown on the card)")
    handle = str(raw.get("handle", "")).strip().removeprefix("@")
    if not HANDLE_RE.fullmatch(handle):
        raise ValueError(f"account.handle {handle!r}: 1-30 letters, digits, dots or underscores")
    avatar = local_file(str(raw["avatar"]), base, AVATAR_SUFFIXES, "account.avatar") if raw.get("avatar") else None
    return Account(handle, str(raw.get("display_name", "")).strip(), avatar)


def load_config(path: Path) -> ReelConfig:
    """Read ``reel_config.json``; ``head`` is mandatory. File names inside it are relative to the config's folder."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "head" not in raw:
        raise ValueError("reel_config.json needs a measured «head» {left, top, right, chin}")
    scalars = {k: raw[k] for k in ("split_air", "face_pad", "face_margin", "track_smooth") if k in raw}
    unknown = set(raw) - set(scalars) - {"head", "colours", "fit", "captions", "account", "assets_dir", "ui_kit", "brand_mentions"}
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    base = path.resolve().parent
    assets = (base / str(raw["assets_dir"])).resolve() if "assets_dir" in raw else (base / "assets").resolve()
    if "assets_dir" in raw and not assets.is_dir():
        raise ValueError(f"assets_dir {assets} is not a folder")
    # The resolved folder (the standard assets/ too) must stay inside the config's folder: "/", "..", a link out are refused.
    if not assets.is_relative_to(base):
        raise ValueError(f"assets_dir {raw.get('assets_dir', 'assets')!r} resolves to {assets}, which is not inside {base} (no absolute path, parent step or link out of the reel folder)")
    ui_kit = None
    if "ui_kit" in raw:
        ui_kit = (base / str(raw["ui_kit"])).resolve()
        if not ui_kit.is_relative_to(base) or not (ui_kit / "components").is_dir():
            raise ValueError(f"ui_kit {raw['ui_kit']!r} must be a folder inside {base} with components/ (a copy of html-components)")
    return ReelConfig(
        assets_dir=assets if assets.is_dir() else None,
        ui_kit=ui_kit,
        brand_mentions=(local_file(str(raw["brand_mentions"]), base, (".json",), "brand_mentions")
                        if "brand_mentions" in raw else None),
        head=_sub(geo.Head, raw["head"]),
        colours=_sub(Colours, raw.get("colours")),
        fit=_sub(FitStyle, raw.get("fit")),
        captions=_sub(CaptionStyle, raw.get("captions")),
        account=_account(raw.get("account"), path.resolve().parent),
        **scalars,
    )
