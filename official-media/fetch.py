"""Fetch the pinned publisher marks for local use. No model account is required."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen


def prepare(root):
    records = json.loads((root/"catalog.json").read_text(encoding="utf-8"))
    for entry in records:
        filename = entry["file"]
        if Path(filename).name != filename or not filename.endswith(".png"):
            raise ValueError("Invalid logo filename")
        target = root / filename
        if target.is_file() and sha256(target.read_bytes()).hexdigest() == entry["sha256"]:
            continue
        request = Request(entry["source_url"], headers={"User-Agent":"ReelEditor-AssetSetup/1.0"})
        with urlopen(request, timeout=40) as response:
            image = response.read(1024*1024+1)
        if not image.startswith(b"\x89PNG\r\n\x1a\n") or sha256(image).hexdigest() != entry["sha256"]:
            raise ValueError(f"Publisher file differs from the pinned release: {filename}")
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(image)
        try:
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
        print(f"Verified {filename}")


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parent / "ai-brands")
