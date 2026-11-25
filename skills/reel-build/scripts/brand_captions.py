"""Attach local brand images to their spoken words inside the measured caption box."""
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from reel_config import ReelConfig, local_file
from reel_plan import Word, normalise


@dataclass(frozen=True)
class BrandMention:
    name: str
    start: float
    end: float
    source: Path
    target: str
    words: tuple[Word, ...]


def _check_svg(source: Path) -> None:
    """Only static, local SVG images. No active or externally referenced content."""
    text = source.read_text(encoding="utf-8")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", text, re.I):
        raise ValueError("brand image contains external declarations")
    root = ET.fromstring(text)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("brand image must be SVG")
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in {"script","foreignobject","image","style","a","animate","animatemotion","animatetransform","set","iframe","feimage"}:
            raise ValueError("brand image requires static vector shapes")
        for attr, value in node.attrib.items():
            key = attr.rsplit("}", 1)[-1].lower()
            if key.startswith("on") or key == "style":
                raise ValueError("brand image contains active attributes")
            if (key in {"href","src","base"} and not value.startswith("#")) or re.search(r"url\(\s*['\"]?(?![#'\"])", value, re.I):
                raise ValueError("brand image contains an external reference")


def load_mentions(cfg: ReelConfig, words: list[Word]) -> list[BrandMention]:
    if cfg.brand_mentions is None:
        return []
    raw = json.loads(cfg.brand_mentions.read_text(encoding="utf-8"))
    items = raw.get("mentions") if isinstance(raw,dict) else None
    if not isinstance(items,list):
        raise ValueError("brand manifest must contain a mentions array")
    result = []
    for item in items:
        if not cfg.assets_dir or not isinstance(item, dict):
            raise ValueError("brand mentions require a local assets directory and object entries")
        start, end = item["start"], item["end"]
        if not all(type(v) in {float,int} and math.isfinite(v) for v in (start,end)) or not 0 <= start < end:
            raise ValueError("invalid brand time interval")
        spoken = item["spoken"]
        name = item["name"]
        if not isinstance(name,str) or not name.strip() or not isinstance(spoken,str):
            raise ValueError("brand mention must include a name and spoken phrase")
        # Re-check the mention against the frozen cut word list; same words on the raw take may have different times.
        seq = normalise(spoken)
        candidates = []
        if "word_start" in item or "word_end" in item:
            first, last = item.get("word_start"), item.get("word_end")
            if type(first) is not int or type(last) is not int or not 0 <= first <= last < len(words):
                raise ValueError("invalid brand word indices")
            span = tuple(words[first:last + 1])
            if (normalise(" ".join(w.w for w in span)) == seq
                    and abs(min(w.start for w in span) - start) <= 0.0011
                    and abs(max(w.end for w in span) - end) <= 0.0011):
                candidates.append(span)
        else:
            for i, word in enumerate(words):
                if abs(word.start-start) > 0.0011:
                    continue
                seen = ""
                for j in range(i,len(words)):
                    seen += words[j].norm
                    if seen == seq and abs(words[j].end-end) <= 0.0011:
                        candidates.append(tuple(words[i:j+1]))
                    if len(seen)>=len(seq):
                        break
        if not seq or len(candidates)!=1:
            raise ValueError(f"brand phrase does not match frozen transcript at {start:.3f}s")
        src = local_file(str(item["file"]), cfg.assets_dir, (".svg",".png",".jpg",".jpeg",".webp"), "brand asset")
        if src.suffix.lower()==".svg":
            _check_svg(src)
        digest = sha256(src.read_bytes()).hexdigest()[:24]
        result.append(BrandMention(name,start,end,src,f"assets/brands/{digest}{src.suffix.lower()}",candidates[0]))
    result.sort(key=lambda m:m.start)
    if any(a.end>b.start+0.001 for a,b in zip(result,result[1:])):
        raise ValueError("overlapping brand mentions")
    return result
