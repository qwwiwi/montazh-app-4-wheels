"""Component library (qwwiwi/html-components) as the visual system of a reel.

The library's components are web blocks at a 16 px base: one ``<style>`` scoped by the prefix ``hc-<id>`` plus markup. A reel scene
built from a component takes that stylesheet as it is and adapts it to a 1080 px video frame (``component_css``):

* the ``@media`` blocks go (they are breakpoints for a phone browser, the frame is always 1080 px wide);
* every class that is not the component's own (``card``, ``btn``, ``tag``, ``eyebrow``, ``mono`` ...) is renamed to ``x-<name>``, so it
  never meets the reel's own classes (``.card`` is the reel's measured card, ``.btn`` its button);
* every length in px is multiplied by ``UI_SCALE`` (2.2: the 16 px body text becomes 35 px);
* type is never below the reel's floors after scaling: 32 px for text, 40 px for monospace (the gate's ``MIN_TEXT_PX`` / ``MIN_MONO_PX``).

The fonts of the library (Inter Tight, JetBrains Mono, variable woff2) are copied into the project; ``font_faces`` declares them.
Nothing is downloaded: the kit is a folder the owner supplied next to ``reel_config.json`` (``"ui_kit": "html-components"``).
"""

from __future__ import annotations

import re
from pathlib import Path

UI_SCALE = 2.2
UI_FONT = "Inter Tight"
TEXT_FLOOR = 32.0
MONO_FLOOR = 40.0
FONT_FILES = {
    "inter-cyr": "InterTight-var-cyrillic.woff2",
    "inter-lat": "InterTight-var-latin.woff2",
    "jbm-cyr": "JetBrainsMono-var-cyrillic.woff2",
    "jbm-lat": "JetBrainsMono-var-latin.woff2",
}
_PX = re.compile(r"(?<![\w.#])(\d*\.?\d+)px")
_CLASS = re.compile(r"\.(?!hc-)(-?[A-Za-z_][\w-]*)")
_FONT_SIZE = re.compile(r"font-size\s*:\s*([0-9.]+)px")
_FONT_SHORT = re.compile(r"(font\s*:[^;{}]*?)(?<![\d.])([0-9.]+)px")

# Wrapper of a component inside a scene: a measured reel card (``.card`` = box for the gate) without the reel's border and shadow;
# the component inside draws its own surfaces.
WRAP_CSS = """
.card.hcw { background:transparent; border:0; border-radius:0; box-shadow:none; overflow:visible; color:inherit; }
.bgd .card.hcw { box-shadow:none; }
.hcw > [class$="-root"] { width:100%; height:100%; }
"""


def component_file(kit: Path, comp_id: str) -> Path:
    """``landing-feature-list`` -> ``<kit>/components/landing/feature-list.html``.

    Raises:
        ValueError: when the id is malformed or the file is not in the kit.
    """
    if not re.fullmatch(r"[a-z]+-[a-z0-9-]+", comp_id):
        raise ValueError(f"component id {comp_id!r}: expected <category>-<name>")
    category, name = comp_id.split("-", 1)
    path = kit / "components" / category / f"{name}.html"
    if not path.is_file():
        raise ValueError(f"component {comp_id!r} not found in {kit} ({path})")
    return path


def drop_media(css: str) -> str:
    """Remove every ``@media`` block (balanced braces)."""
    out, i = [], 0
    while True:
        k = css.find("@media", i)
        if k < 0:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:k])
        j = css.index("{", k)
        depth = 0
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1


def _rename_selectors(css: str) -> str:
    """Prefix foreign classes with ``x-`` in selectors only (declarations keep their numbers like ``.5``)."""
    out = []
    for chunk in re.split(r"(\{[^{}]*\})", css):
        out.append(chunk if chunk.startswith("{") else _CLASS.sub(r".x-\1", chunk))
    return "".join(out)


def _scale_px(css: str, k: float) -> str:
    return _PX.sub(lambda m: f"{round(float(m.group(1)) * k, 2):g}px", css)


def _floor_fonts(css: str) -> str:
    """Raise every font size of a rule to the floor: 40 px when the rule is monospace, else 32 px."""
    out = []
    parts = re.split(r"(\{[^{}]*\})", css)
    selector = ""
    for chunk in parts:
        if not chunk.startswith("{"):
            selector = chunk
            out.append(chunk)
            continue
        mono = "mono" in selector or "var(--mono)" in chunk
        floor = MONO_FLOOR if mono else TEXT_FLOOR
        chunk = _FONT_SIZE.sub(lambda m: f"font-size:{max(float(m.group(1)), floor):g}px", chunk)
        chunk = _FONT_SHORT.sub(lambda m: f"{m.group(1)}{max(float(m.group(2)), floor):g}px", chunk)
        out.append(chunk)
    return "".join(out)


def adapt_css(css: str, k: float = UI_SCALE) -> str:
    """The component stylesheet adapted to the video frame (see the module docstring)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return _floor_fonts(_scale_px(_rename_selectors(drop_media(css)), k)).strip()


def component_css(kit: Path, comp_id: str, k: float = UI_SCALE) -> str:
    """Read the component's ``<style>`` from the kit and adapt it."""
    text = component_file(kit, comp_id).read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", text, flags=re.S)
    if not m:
        raise ValueError(f"component {comp_id!r} has no <style>")
    return f"/* {comp_id} (html-components, x{k:g}) */\n" + adapt_css(m.group(1), k)


def font_files(kit: Path) -> dict[str, Path]:
    """Font files of the kit by their project name.

    Raises:
        ValueError: when a font file is missing.
    """
    out = {}
    for name, file in FONT_FILES.items():
        path = kit / "fonts" / file
        if not path.is_file():
            raise ValueError(f"ui kit font {path} is missing")
        out[name] = path
    return out


def font_faces(cyr: str, lat: str) -> str:
    """``@font-face`` rules of the kit's fonts (files copied to ``assets/fonts``)."""
    rules = []
    for family, stem, weights in ((UI_FONT, "inter", "100 900"), ("JetBrains Mono", "jbm", "100 800")):
        for sub, rng in (("cyr", cyr), ("lat", lat)):
            rules.append(f"@font-face {{ font-family:'{family}'; src:url('assets/fonts/{stem}-{sub}.woff2') format('woff2'); "
                         f"font-weight:{weights}; unicode-range:{rng}; }}")
    return "\n".join(rules)
