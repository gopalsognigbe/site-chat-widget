"""Convert generated PNGs in demo_site/img/src to WebP (full + small), copying
each image's provenance (prompt, model, task) into the WebP metadata and a JSON sidecar."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "img-src"
OUT = ROOT / "demo_site" / "img"

# name: (full width, small width)
SIZES = {"hero": (1344, 960), **{n: (900, 640) for n in ("n-plateau", "n-griffintown", "n-verdun", "n-ndg", "n-oldmtl")}}
DEFAULT = (1200, 640)


def convert(png: Path) -> None:
    name = png.stem
    full, small = SIZES.get(name, DEFAULT)
    meta_path = png.with_name(png.name + ".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    xmp = json.dumps({"provenance": meta}, ensure_ascii=False).encode()
    im = Image.open(png).convert("RGB")
    for width, suffix in ((full, ""), (small, f"-{small}")):
        h = round(im.height * width / im.width)
        out = OUT / f"{name}{suffix}.webp"
        im.resize((width, h), Image.LANCZOS).save(out, "WEBP", quality=80, method=6, xmp=xmp)
        print(f"{out.name} {width}x{h} {out.stat().st_size // 1024} KB")
    (OUT / f"{name}.webp.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    for p in sorted(SRC.glob("*.png")) if len(sys.argv) < 2 else [SRC / f"{a}.png" for a in sys.argv[1:]]:
        convert(p)
