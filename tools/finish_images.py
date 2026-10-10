# SPDX-License-Identifier: GPL-3.0-or-later
"""Crop and compress the screenshots of tools/capture_examples.py into docs/rules/.

    python tools/finish_images.py CAPTURE_DIR [OUT_DIR]

Needs Pillow. Each screenshot is cropped to the box in CAPTURE_DIR/boxes.json and saved as a
palette PNG (256 colours, no dithering: node editor screenshots have few colours).
"""
import json
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(src, out):
    """Crop, quantize and save every image listed in src/boxes.json."""
    with open(os.path.join(src, "boxes.json"), encoding="utf-8") as fh:
        boxes = json.load(fh)
    os.makedirs(out, exist_ok=True)
    for name, box in sorted(boxes.items()):
        im = Image.open(os.path.join(src, name + ".png")).convert("RGB")
        box = [max(0, box[0]), max(0, box[1]), min(im.width, box[2]), min(im.height, box[3])]
        im = im.crop(box).quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        path = os.path.join(out, name + ".png")
        im.save(path, optimize=True)
        print(f"{os.path.relpath(path, ROOT)}: {im.width}x{im.height}, {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "docs", "rules"))
