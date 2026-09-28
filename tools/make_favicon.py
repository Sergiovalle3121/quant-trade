"""Render the tab icon and the home-screen icon in ``static/`` from the brand mark.

- ``favicon.ico``: the mark at 16, 32 and 48 pixels, for ``/favicon.ico``.
- ``apple-touch-icon.png``: the mark at 180 pixels on a full square (the phone
  rounds the corners itself), for ``/apple-touch-icon.png``.

The drawing is the one ``theme.FAVICON`` and ``theme.logo_mark`` show: a dark
rounded square, a bell curve and a threshold line. Only the standard library is
used and nothing depends on the clock, so the same files come out every time:
python tools/make_favicon.py [output_dir]
"""

import struct
import sys
import zlib
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "quant_trade" / "audit" / "static"

#: The mark is drawn in a 32-unit box, like the SVG's ``viewBox``.
BOX = 32.0
CORNER = 9.0
BACKGROUND = (0x11, 0x11, 0x13)
CURVE = (0xF4, 0xF4, 0xF6)
CURVE_WIDTH = 2.2
THRESHOLD = (0x8A, 0x8A, 0x90)
THRESHOLD_WIDTH = 2.0
#: ``M5 23c3.5 0 5-11 11-11s7.5 11 11 11`` as two cubic curves.
CURVE_PARTS = (
    ((5.0, 23.0), (8.5, 23.0), (10.0, 12.0), (16.0, 12.0)),
    ((16.0, 12.0), (22.0, 12.0), (23.5, 23.0), (27.0, 23.0)),
)
#: ``M20.5 7v18``.
THRESHOLD_LINE = ((20.5, 7.0), (20.5, 25.0))
ICO_SIZES = (16, 32, 48)
APPLE_SIZE = 180
#: Points sampled per pixel side: 4 means 16 samples a pixel.
SAMPLES = 4

Point = tuple[float, float]
Pixel = tuple[int, int, int, int]


def _curve_points(steps: int = 24) -> list[Point]:
    points: list[Point] = [CURVE_PARTS[0][0]]
    for p0, p1, p2, p3 in CURVE_PARTS:
        for i in range(1, steps + 1):
            t = i / steps
            u = 1 - t
            points.append(
                (
                    u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
                )
            )
    return points


def _near(x: float, y: float, line: list[Point], reach: float) -> bool:
    """Whether (x, y) is within ``reach`` of the line (round caps and joins)."""
    limit = reach * reach
    for (ax, ay), (bx, by) in zip(line, line[1:], strict=False):
        dx, dy = bx - ax, by - ay
        t = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
        t = min(1.0, max(0.0, t))
        ex, ey = x - (ax + t * dx), y - (ay + t * dy)
        if ex * ex + ey * ey <= limit:
            return True
    return False


def _inside_square(x: float, y: float) -> bool:
    cx = min(max(x, CORNER), BOX - CORNER)
    cy = min(max(y, CORNER), BOX - CORNER)
    return (x - cx) ** 2 + (y - cy) ** 2 <= CORNER * CORNER


def render(size: int, *, full_square: bool = False) -> list[list[Pixel]]:
    """The mark as rows of (red, green, blue, alpha) pixels, top row first."""
    curve = _curve_points()
    threshold = list(THRESHOLD_LINE)
    curve_top = min(y for _, y in curve) - CURVE_WIDTH / 2
    curve_bottom = max(y for _, y in curve) + CURVE_WIDTH / 2
    scale = BOX / (size * SAMPLES)
    total = SAMPLES * SAMPLES
    rows: list[list[Pixel]] = []
    for py in range(size):
        row: list[Pixel] = []
        for px in range(size):
            red = green = blue = covered = 0
            for sy in range(SAMPLES):
                y = (py * SAMPLES + sy + 0.5) * scale
                for sx in range(SAMPLES):
                    x = (px * SAMPLES + sx + 0.5) * scale
                    if not (full_square or _inside_square(x, y)):
                        continue
                    colour = BACKGROUND
                    if curve_top <= y <= curve_bottom and _near(x, y, curve, CURVE_WIDTH / 2):
                        colour = CURVE
                    if _near(x, y, threshold, THRESHOLD_WIDTH / 2):
                        colour = THRESHOLD
                    red += colour[0]
                    green += colour[1]
                    blue += colour[2]
                    covered += 1
            if covered == 0:
                row.append((0, 0, 0, 0))
                continue
            row.append(
                (
                    (red + covered // 2) // covered,
                    (green + covered // 2) // covered,
                    (blue + covered // 2) // covered,
                    (255 * covered + total // 2) // total,
                )
            )
        rows.append(row)
    return rows


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def png_bytes(rows: list[list[Pixel]]) -> bytes:
    """An 8-bit RGBA PNG."""
    size = len(rows)
    raw = b"".join(b"\x00" + bytes(v for pixel in row for v in pixel) for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def _ico_image(rows: list[list[Pixel]]) -> bytes:
    """One icon image: a 32-bit bitmap, bottom row first, and its 1-bit mask."""
    size = len(rows)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    colour = b"".join(
        bytes(v for r, g, b, a in row for v in (b, g, r, a)) for row in reversed(rows)
    )
    mask_row = (size + 31) // 32 * 4
    mask = b""
    for row in reversed(rows):
        bits = bytearray(mask_row)
        for x, pixel in enumerate(row):
            if pixel[3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bytes(bits)
    return header + colour + mask


def ico_bytes(sizes: tuple[int, ...] = ICO_SIZES) -> bytes:
    images = [_ico_image(render(size)) for size in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, image in zip(sizes, images, strict=True):
        out += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    return out + b"".join(images)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else STATIC_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "favicon.ico").write_bytes(ico_bytes())
    (out / "apple-touch-icon.png").write_bytes(png_bytes(render(APPLE_SIZE, full_square=True)))
    print(f"wrote favicon.ico and apple-touch-icon.png in {out}")


if __name__ == "__main__":
    main()
