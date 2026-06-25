"""Validate release screenshots and build a compact visual-QA contact sheet."""
from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageStat


def validate(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    if image.width < 1000 or image.height < 700:
        raise ValueError("%s is unexpectedly small: %sx%s" % (path, image.width, image.height))
    deviation = ImageStat.Stat(image.resize((128, 96))).stddev
    if max(deviation) < 8:
        raise ValueError("%s appears blank or nearly uniform" % path)
    return image


def main(arguments: list[str]) -> int:
    paths = [Path(value) for value in arguments]
    if not paths:
        raise ValueError("Provide at least one screenshot.")
    images = [(path, validate(path)) for path in paths]

    thumb_width, thumb_height = 420, 270
    columns = 3
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_width, rows * (thumb_height + 28)), "#0d1117")
    draw = ImageDraw.Draw(sheet)
    for index, (path, image) in enumerate(images):
        image.thumbnail((thumb_width, thumb_height))
        x = (index % columns) * thumb_width
        y = (index // columns) * (thumb_height + 28)
        sheet.paste(image, (x, y))
        draw.text((x + 6, y + thumb_height + 6), path.stem, fill="#c9d1d9")
    output = paths[0].parent / "ui-contact-sheet.png"
    sheet.save(output)
    print("Validated %d screenshots; contact sheet: %s" % (len(images), output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
