"""Adapt the editor's explicit source-only shots to first-class HyperFrames scenes."""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from html import escape
from pathlib import Path
import re
import shutil
import sys

from source_assets import source_manifest


_material = ContextVar("reel_source_material", default=None)
KIND = "publisher_capture"


@contextmanager
def using_material(material):
    token = _material.set(material)
    try:
        yield
    finally:
        _material.reset(token)


def adapt(raw, src, rp, words):
    """Return a renderer plan and actual media placements without mutating Opus's plan."""
    if any(s.get("kind") == KIND for s in raw.get("scenes", [])):
        raise ValueError("Publisher capture scenes must be derived from the registered source and word cue.")
    material = _material.get()
    if not material:
        return raw, None
    manifest = source_manifest(material, src, raw)
    shots = raw["shots"]
    scenes = list(raw.get("scenes", []))
    occupied = {s["shot"] for s in scenes}
    bounds = [0] + [rp.resolve(s["from"], words, src["duration"], lead=rp.LEAD) for s in shots[1:]] + [rp.snap(src["duration"])]
    assets = {a["id"]: a for a in manifest["assets"]}
    for idx, shot in enumerate(shots):
        if idx in occupied or shot["type"] not in ("visual", "split") or not shot.get("source"):
            continue
        asset = assets.get(shot["source"])
        # The renderer leads a word-anchored cut by 60 ms, plus frame quantization.
        tolerance = rp.LEAD + 1/30 + 1e-6
        start, end = bounds[idx:idx+2]
        match = next((p for p in manifest["placements"] if p["asset_id"] == shot["source"]
                      and "native_shot" not in p and abs(p["start"]-start) <= tolerance
                      and abs(p["end"]-end) <= tolerance), None)
        if not asset or not match or not raw.get("source_cues"):
            raise ValueError(f"Source-only shot {idx} requires a supplied image and an explicit word cue spanning its shot.")
        digest = asset.get("screenshot_sha256", "")
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError(f"Source-only shot {idx} has no verified image digest.")
        match.update(native_shot=idx, start=start, end=end)
        scenes.append({"shot": idx, "kind": KIND, "bg": "dark", "digest": digest,
                       "title": asset["title"], "credit": asset["credit"]})
    if len(scenes) == len(raw.get("scenes", [])):
        return raw, manifest
    return {**raw, "scenes": sorted(scenes, key=lambda s:s["shot"])}, manifest


def renderer_plan(raw, transcript, skill):
    # An audio-only resume can reach the build without importing the planner.
    sys.path.insert(0, str((Path(skill)/"scripts").resolve()))
    try:
        import reel_plan as rp
        words = [rp.Word(w["w"], w["start"], w["end"]) for w in transcript["words"]]
        return adapt(raw, transcript, rp, words)
    finally:
        sys.path.pop(0)


def prepare_images(folder, assets_dir, manifest):
    native_ids = {p["asset_id"] for p in manifest["placements"] if "native_shot" in p}
    for asset in manifest["assets"]:
        if asset["id"] not in native_ids:
            continue
        filename = asset.get("file","source.png")
        if Path(filename).name != filename:
            raise ValueError("Invalid publisher capture filename.")
        path = folder / filename
        digest = asset["screenshot_sha256"]
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Source screenshot checksum mismatch.")
        shutil.copyfile(path, assets_dir / (digest+".png"))


def build(builder, data):
    digest = data["digest"]
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("Invalid publisher capture digest.")
    image = builder.ctx.assets_dir / (digest+".png")
    if sha256(image.read_bytes()).hexdigest() != digest:
        raise ValueError("Publisher scene pixels differ from the verified capture.")
    url = builder.asset(image, "assets/sources", digest)
    caption = escape(data["title"]) + " · " + escape(data["credit"])
    builder.add(f'<figure style="margin:0;width:960px;height:100%;display:flex;flex-direction:column;'
                f'justify-content:center;gap:12px"><img src="{url}" alt="" style="min-height:0;max-height:85%;'
                'width:100%;object-fit:contain;background:#fff;border-radius:10px">'
                f'<figcaption style="font:600 32px/1.2 sans-serif;color:white">{caption}</figcaption></figure>')
    builder.state(builder.t0)


if __name__ == "__main__":
    # Run the configured skill unchanged, adding just its publisher scene renderer.
    import sys
    sys.path.insert(0, sys.argv[1])
    import scenes
    import reel
    scenes.BUILDERS[KIND] = build
    raise SystemExit(reel.main(sys.argv[2:]))
