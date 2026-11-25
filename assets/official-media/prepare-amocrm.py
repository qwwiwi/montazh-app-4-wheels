"""Prepare optional local amoCRM source images from the publisher; never send footage."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from datetime import datetime, timezone

HOME_URL = "https://www.amocrm.ru/"
SPRITE = HOME_URL + "static/images/sprite.png?070720161242"
GUIDE = HOME_URL + "static/assets/education/amocrm_2_instruction.pdf"
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retrieve(url, checksum, dest):
    subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                    "--proto", "=https", "--proto-redir", "=https", "--max-time", "120",
                    "--retry", "1", "--output", str(dest), url], check=True)
    if digest(dest) != checksum:
        raise ValueError(f"Publisher bytes changed for {url}. Review the new file before updating the pin.")


def image_size(path):
    header = path.read_bytes()[:24]
    if not header.startswith(b"\x89PNG\r\n\x1a\n") or header[12:16] != b"IHDR":
        raise ValueError(f"Expected a PNG: {path.name}")
    return struct.unpack(">II", header[16:24])


def crop(source, dest, rect):
    width,height,x,y = rect
    subprocess.run(["ffmpeg","-nostdin","-loglevel","error","-i",str(source),
                    "-vf",f"format=rgba,crop={width}:{height}:{x}:{y}","-frames:v","1",str(dest)],check=True)


def chrome():
    candidates = [os.environ.get("REEL_CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")]
    for name in candidates:
        if name and os.access(name,os.X_OK):
            return name
    raise ValueError("Install Chrome or set REEL_CHROME to the browser executable.")


def prepare(dest):
    if dest.exists():
        # Keep any locally customized material intact and verify an existing preparation.
        manifest = json.loads((dest/"source.json").read_text())
        for asset in [manifest, *manifest["related_sources"]]:
            if digest(dest/asset["file"]) != asset["screenshot_sha256"]:
                raise ValueError("Existing local image differs from its manifest.")
        if digest(dest/"logo.png") != manifest["logo"]["sha256"]:
            raise ValueError("Existing local logo differs from its manifest.")
        print(f"Verified existing bundle: {dest}")
        return
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".prepare-amo-") as tmp:
        temp=Path(tmp)
        bundle=temp/"amocrm"
        bundle.mkdir()
        retrieve(SPRITE,"a56443bee3920d165c8d51d1e947c0dffa96385c52d3e7b25763d5c8beb93de7",temp/"sprite.png")
        retrieve(GUIDE,"e5bb80f61c67c0942abfc535b90e945425c578a5a0a6fcf2b43de06070b78359",temp/"guide.pdf")
        crop(temp/"sprite.png",bundle/"logo.png",(151,31,0,724))
        subprocess.run(["node", str(HERE/"capture-amocrm.cjs"),str(bundle/"source.png"),chrome()],check=True)
        if image_size(bundle/"source.png") != (1260,800):
            raise ValueError("Unexpected browser viewport.")
        related=[]
        for name,page,index,size,rect,title,phrases in [
                ("inbox",34,4,(3709,2159),(2240,1480,1410,178),"История общения",["переписка","сообщения","общение"]),
                ("pipeline",36,2,(3639,1227),(2450,1220,0,0),"Воронка продаж",["воронка","воронке","сделки"])]:
            prefix=temp/name
            subprocess.run(["pdfimages","-f",str(page),"-l",str(page),"-png",str(temp/"guide.pdf"),str(prefix)],check=True)
            src=temp/f"{name}-{index:03d}.png"
            if image_size(src) != size:
                raise ValueError(f"Unexpected figure for guide page {page}.")
            destfile=bundle/f"{name}.png"
            crop(src,destfile,rect)
            related.append({"id":"amocrm-"+name,"title":"amoCRM · "+title,"file":destfile.name,"kind":"screenshot",
                            "source_url":f"{GUIDE}#page={page}","credit":f"amoCRM · PDF, стр. {page}",
                            "rights":"Publisher training manual, credited screenshot; reuse license unverified.",
                            "cue_phrases":phrases,"screenshot_sha256":digest(destfile)})
        meta={"id":"amocrm-home","file":"source.png","kind":"website","title":"amoCRM","phrase":"amoCRM",
              "cue_phrases":["amoCRM","амо срм"],"source_url":HOME_URL,"credit":"amocrm.ru",
              "rights":"Publisher website screenshot; reuse license unverified.","screenshot_sha256":digest(bundle/"source.png"),
              "captured_at":datetime.now(timezone.utc).isoformat(),"related_sources":related,
              "logo":{"source_url":SPRITE,"css_url":HOME_URL+"static/app_index.css?1795614775",
                      "xywh":[0,724,151,31],"sha256":digest(bundle/"logo.png")}}
        (bundle/"source.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        bundle.rename(dest)
        print(f"Prepared {dest}")


if __name__ == "__main__":
    prepare(HERE/"amocrm")
