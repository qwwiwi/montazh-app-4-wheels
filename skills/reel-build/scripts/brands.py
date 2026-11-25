"""Resolve spoken brand names to approved, passive, local SVG marks."""
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET


SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)
BRAND_ID = re.compile(r"[\w-]+(?::[\w.-]+)?(?:/[\w.-]+)*")
XML_ID = r"[A-Za-z_][\w.:-]*"
LOCAL_PAINT = re.compile(r"url\(#(" + XML_ID + r")\)")
TAGS = set("svg title desc g path circle rect ellipse line polyline polygon defs linearGradient radialGradient stop clipPath mask".split())
ATTRS = set(("id viewBox width height x y x1 y1 x2 y2 rx ry r cx cy fx fy fr d points fill fill-rule "
             "fill-opacity stroke stroke-width stroke-linejoin stroke-linecap stroke-miterlimit stroke-opacity "
             "stroke-dasharray stroke-dashoffset opacity transform clip-path clip-rule clipPathUnits mask maskUnits "
             "maskContentUnits gradientUnits gradientTransform spreadMethod offset stop-color stop-opacity "
             "preserveAspectRatio role aria-label aria-labelledby aria-hidden focusable version color").split())


PAINT_PROPS = set(("fill fill-rule fill-opacity stroke stroke-width stroke-linejoin stroke-linecap "
                   "stroke-miterlimit stroke-opacity stroke-dasharray stroke-dashoffset opacity "
                   "clip-path clip-rule mask mask-type color stop-color stop-opacity enable-background").split())
ATTRS.update(PAINT_PROPS)
CLASS = r"[A-Za-z_][A-Za-z0-9_-]*"


def paint_declarations(style):
    props = {}
    for declaration in style.split(";"):
        if not declaration.strip():
            continue
        prop, sep, val = declaration.partition(":")
        prop, val = prop.strip(), val.strip()
        if prop not in PAINT_PROPS or not sep or not val or len(val)>512:
            raise ValueError("SVG style property")
        props[prop]=val
    return props


def flatten_paint_styles(root, prefix):
    # Expand vector editors' simple class rules to presentation attributes.
    # Decline any stylesheet that needs selectors, imports, animations or fonts.
    rules=[]
    for parent in root.iter():
        for sheet in list(parent):
            if sheet.tag not in ("style",prefix+"style"):
                continue
            if len(sheet) or any(k!="type" or v!="text/css" for k,v in sheet.attrib.items()):
                raise ValueError("SVG stylesheet")
            css=re.sub(r"/\*.*?\*/","",sheet.text or "",flags=re.S).strip()
            while css:
                match=re.match(r"([^{}]+)\{([^{}]*)\}",css)
                if not match:
                    raise ValueError("SVG stylesheet")
                selectors=[c.strip() for c in match[1].split(",")]
                if not all(re.fullmatch(r"\."+CLASS,c) for c in selectors) or len(rules)>=512:
                    raise ValueError("SVG stylesheet selector")
                rules.append(({c[1:] for c in selectors},paint_declarations(match[2])))
                css=css[match.end():].lstrip()
            parent.remove(sheet)
    for el in root.iter():
        if "class" in el.attrib:
            names=set(el.attrib.pop("class").split())
            if not all(re.fullmatch(CLASS,n) for n in names):
                raise ValueError("SVG class")
            for selectors, props in rules:
                if names & selectors:
                    el.attrib.update(props)
        inline=el.attrib.pop("style","")
        if inline and el is root:
            inline=';'.join(part for part in inline.split(';') if part.replace(' ','').lower() not in {'flex:none','line-height:1'})
        if inline:
            el.attrib.update(paint_declarations(inline))
        # Non-rendering labels left by vector editors.
        el.attrib.pop("data-name",None)
        el.attrib.pop("{http://www.w3.org/XML/1998/namespace}space",None)


def safe_svg(data):
    """Allow fixed vector geometry, colors, and fragment references within this image."""
    if not data or len(data) > 1024 * 1024:
        raise ValueError("SVG size")
    text = data.decode("utf-8-sig")
    stripped = re.sub(r"^\s*<\?xml\s+[^?]*\?>", "", text, count=1, flags=re.I)
    if "<?" in stripped or re.search(r"<!\s*(?:DOCTYPE|ENTITY|\[CDATA)", stripped, re.I):
        raise ValueError("SVG declaration")
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError as e:
        raise ValueError("SVG XML") from e
    prefix = "{"+SVG+"}"
    if root.tag not in ("svg", prefix+"svg"):
        raise ValueError("SVG root")
    flatten_paint_styles(root,prefix)
    ids, refs = set(), set()
    node_count = 0
    for el in root.iter():
        node_count += 1
        tag = el.tag.removeprefix(prefix)
        if tag not in TAGS or node_count > 10000:
            raise ValueError("SVG element")
        if (el.text or "").strip() and tag not in {"title", "desc"}:
            raise ValueError("SVG geometry text")
        if (el.tail or "").strip():
            raise ValueError("SVG tail")
        el.tag = prefix + tag
        for attr, value in el.attrib.items():
            if attr not in ATTRS:
                raise ValueError("SVG attribute")
            if attr == "id":
                if not re.fullmatch(XML_ID, value) or value in ids:
                    raise ValueError("SVG id")
                ids.add(value)
            if attr.startswith("aria-") or attr == "role":
                continue
            if re.search(r"url\s*\(|[\\;@<>\x00-\x08]|(?:https?|data|file|javascript):", value, re.I):
                local = LOCAL_PAINT.fullmatch(value)
                if not local or attr not in ("fill", "stroke", "clip-path", "mask"):
                    raise ValueError("SVG resource")
                refs.add(local[1])
    if refs - ids:
        raise ValueError("Unknown SVG reference")
    box = root.get("viewBox", "").strip()
    if box:
        coords = [float(v) for v in re.split(r"[\s,]+", box)]
        if len(coords) != 4 or not all(math.isfinite(v) for v in coords) or min(coords[2:]) <= 0:
            raise ValueError("SVG viewBox")
    else:
        lengths = [root.get(a, "") for a in ("width","height")]
        if not all(re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:px)?", v) for v in lengths):
            raise ValueError("SVG viewport")
        widths = [float(v.removesuffix("px")) for v in lengths]
        if not all(math.isfinite(v) and v > 0 for v in widths):
            raise ValueError("SVG viewport")
        root.set("viewBox", "0 0 " + " ".join(v.removesuffix("px") for v in lengths))
    root.set("preserveAspectRatio", "xMidYMid meet")
    return ET.tostring(root, encoding="utf-8")


def tokens(value):
    folded = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.findall(r"[^\W_]+|[+#&]", folded)


def load_catalog(path):
    raw = path.read_bytes()
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("Brand catalog exceeds the size limit.")
    entries = json.loads(raw)
    if isinstance(entries,dict):
        entries = entries.get("brands")
    if not isinstance(entries,list):
        raise ValueError("Brand catalog must contain a list of brands.")
    index = defaultdict(list)
    by_id = {}
    for entry in entries:
        if not isinstance(entry,dict):
            raise ValueError("Invalid brand catalog entry.")
        ident, name = entry.get("id"), entry.get("name")
        if (not isinstance(ident,str) or not BRAND_ID.fullmatch(ident) or ident in by_id or len(ident)>240
                or not all(isinstance(entry.get(k),str) and entry[k].strip() for k in ("name","file","source"))
                or not isinstance(entry.get("aliases"),list)):
            raise ValueError("Invalid or duplicated brand catalog entry.")
        by_id[ident] = entry
        enabled = entry.get("auto_match",True)
        needs_context = entry.get("requires_context",False)
        if not isinstance(enabled,bool) or not isinstance(needs_context,bool):
            raise ValueError("auto_match and requires_context must be booleans.")
        aliases=set()
        # A non-empty alias list explicitly defines the autonomous vocabulary.
        for alias in entry["aliases"] or [name]:
            if not isinstance(alias,str) or not alias.strip() or len(alias)>160:
                raise ValueError("Invalid brand alias.")
            parts = tuple(tokens(alias))
            if not parts:
                raise ValueError("Empty normalized brand alias.")
            aliases.add(parts)
        for parts in sorted(aliases):
            index[parts[0]].append((parts, ident, not enabled or needs_context))
        context_aliases=entry.get('context_aliases',[])
        if not isinstance(context_aliases,list):raise ValueError('Invalid context aliases.')
        for alias in context_aliases:
            if not isinstance(alias,str) or not alias.strip():raise ValueError('Invalid context alias.')
            phrase=tuple(tokens(alias))
            if phrase and phrase not in aliases:index[phrase[0]].append((phrase,ident,True))
        canonical=tuple(tokens(name))
        if canonical and canonical not in aliases:
            index[canonical[0]].append((canonical,ident,True))
    return index, by_id, hashlib.sha256(raw).hexdigest()


def copy_asset(entry, base, dest):
    relative = entry["file"]
    path = Path(relative)
    if (path.suffix.lower() != ".svg" or path.is_absolute() or PureWindowsPath(relative).drive
            or ".." in path.parts or any(c in relative for c in ("\\",":","\x00"))):
        raise ValueError("unsafe_asset")
    source = (base/path).resolve()
    if not source.is_relative_to(base.resolve()):
        raise ValueError("unsafe_asset")
    if not source.is_file():
        raise ValueError("missing_asset")
    with source.open("rb") as f:
        data = f.read(1024*1024+1)
    try:
        validated = safe_svg(data)
    except (UnicodeError,ValueError,RecursionError) as err:
        raise ValueError("unsafe_asset") from err
    ident = entry["id"]
    name = ident+".svg" if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}",ident) else (
        re.sub(r"[^a-z0-9_-]","-",ident.lower())[:50]+"-"+hashlib.sha256(ident.encode()).hexdigest()[:12]+".svg")
    dest.mkdir(parents=True,exist_ok=True)
    if dest.is_symlink():
        raise ValueError("unsafe_asset")
    with tempfile.NamedTemporaryFile(dir=dest,delete=False) as out:
        tmp = Path(out.name)
        out.write(validated)
    try:
        os.replace(tmp,dest/name)
    finally:
        tmp.unlink(missing_ok=True)
    return name


def find_matches(words,index,approved):
    pieces,owners,starts,ends = [],[],set(),set()
    for i, w in enumerate(words):
        if not isinstance(w,dict) or not isinstance(w.get("w"),str):
            raise ValueError("Invalid timed word.")
        a,b = w.get("start"),w.get("end")
        if not all(type(v) in (float,int) and math.isfinite(v) for v in (a,b)) or not 0<=a<=b:
            raise ValueError("Invalid word timestamps.")
        chunks=tokens(w["w"])
        if not chunks:
            # Standalone punctuation does not take a logo off an adjacent word.
            continue
        starts.add(len(pieces))
        pieces.extend(chunks)
        owners.extend([i]*len(chunks))
        ends.add(len(pieces))
    found=[]
    contextual=[]
    for i in sorted(starts):
        for alias,ident,conditional in index.get(pieces[i],()):
            end=i+len(alias)
            if end in ends and tuple(pieces[i:end])==alias:
                # A list of separate statements must not form a compound brand.
                l,r=owners[i],owners[end-1]
                if any(words[n+1]["start"]-words[n]["end"]>1.0 for n in range(l,r)):
                    continue
                if conditional:
                    if (l,r) in approved:
                        contextual.append((l,r,ident))
                else:
                    found.append((l,r,ident))
    # Several libraries can carry the same logo. An exact curated alias wins
    # over non-curated catalog titles enabled by a model candidate.
    curated_spans={m[:2] for m in found}
    found.extend(m for m in contextual if m[:2] not in curated_spans)
    return sorted(set(found))


def resolve_groups(found):
    """Prefer a containing phrase; crossed or same-length competing claims need review."""
    group=[]
    right=-1
    for match in found:
        if group and match[0]>right:
            yield group
            group=[]
        group.append(match)
        right=max(m[1] for m in group)
    if group:
        yield group


def prepare_brands(words, catalog, assets_dir, candidates=None):
    """Return resolved and unresolved brand mentions with frozen cut word timing."""
    catalog,assets_dir=Path(catalog),Path(assets_dir)
    if not isinstance(words,dict):
        words=json.loads(Path(words).read_text())
    words=words["words"]
    if not isinstance(words,list):
        raise ValueError("Expected a timed word list.")
    index,by_id,digest=load_catalog(catalog)
    mentions,unresolved=[],[]
    assets={}
    approved=set()
    if candidates is not None and not isinstance(candidates,list):
        raise ValueError("Expected a list of source-grounded brand candidates.")
    for candidate in candidates or []:
        if not isinstance(candidate,dict):
            raise ValueError("Invalid brand candidate.")
        first,last=candidate.get("first"),candidate.get("last")
        if type(first) is not int or type(last) is not int or not 0<=first<=last<len(words):
            raise ValueError("Candidate outside the frozen word list.")
        approved.add((first,last))
    found=find_matches(words,index,approved)
    matched_spans={m[:2] for m in found}
    for first,last in sorted(approved-matched_spans):
        span=words[first:last+1]
        unresolved.append({"ids":[],"reason":"no_catalog_match","word_start":first,"word_end":last,
            "start":min(w["start"] for w in span),"end":max(w["end"] for w in span),
            "spoken":" ".join(w["w"] for w in span)})
    for group in resolve_groups(found):
        l=min(m[0] for m in group)
        r=max(m[1] for m in group)
        spans=words[l:r+1]
        item={"word_start":l,"word_end":r,"start":min(w["start"] for w in spans),
              "end":max(w["end"] for w in spans),"spoken":" ".join(w["w"] for w in spans)}
        widest=[m for m in group if m[:2]==(l,r)]
        if len(widest)!=1:
            unresolved.append(dict(item,ids=sorted({m[2] for m in group}),reason="ambiguous_alias"))
            continue
        ident=widest[0][2]
        entry=by_id[ident]
        if ident not in assets:
            try:
                assets[ident]=(copy_asset(entry,catalog.parent,assets_dir),None)
            except ValueError as err:
                assets[ident]=(None,str(err))
        file,reason=assets[ident]
        if reason:
            unresolved.append(dict(item,ids=[ident],reason=reason))
        else:
            mentions.append(dict(item,id=ident,name=entry["name"],source=entry["source"],file=file))
    return {"mentions":mentions,"unresolved":unresolved,"catalog_sha256":digest}
