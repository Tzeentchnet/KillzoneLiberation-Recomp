#!/usr/bin/env python3
"""Generate the original reticle icon used by the local macOS app bundle."""

from __future__ import annotations

import argparse
import math
import os
import struct
import zlib


ICON_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge0 == edge1:
        return 1.0 if value >= edge1 else 0.0
    scaled = clamp((value - edge0) / (edge1 - edge0))
    return scaled * scaled * (3.0 - 2.0 * scaled)


def rounded_box_distance(x: float, y: float, half: float, radius: float) -> float:
    qx = abs(x) - (half - radius)
    qy = abs(y) - (half - radius)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - radius


def blend(base: tuple[float, float, float], color: tuple[float, float, float],
          amount: float) -> tuple[float, float, float]:
    amount = clamp(amount)
    return tuple(
        base[index] * (1.0 - amount) + color[index] * amount
        for index in range(3)
    )


def pixel(x: float, y: float, antialias: float) -> tuple[int, int, int, int]:
    box = rounded_box_distance(x, y, 0.94, 0.20)
    alpha = 1.0 - smoothstep(-antialias, antialias, box)
    if alpha <= 0.0:
        return 0, 0, 0, 0

    radial = clamp(1.0 - math.hypot(x + 0.12, y - 0.16) / 1.35)
    vertical = clamp((y + 1.0) * 0.5)
    base = (
        18.0 + 20.0 * radial + 8.0 * vertical,
        24.0 + 34.0 * radial + 13.0 * vertical,
        20.0 + 15.0 * radial,
    )

    border = 1.0 - smoothstep(
        0.025 - antialias, 0.025 + antialias, abs(box + 0.035)
    )
    base = blend(base, (114.0, 130.0, 94.0), border * 0.58)

    radius = math.hypot(x, y)
    outer_ring = 1.0 - smoothstep(
        0.025 - antialias, 0.025 + antialias, abs(radius - 0.52)
    )
    inner_ring = 1.0 - smoothstep(
        0.018 - antialias, 0.018 + antialias, abs(radius - 0.24)
    )
    cross_vertical = (
        (1.0 - smoothstep(0.022, 0.022 + antialias, abs(x)))
        * smoothstep(0.27, 0.33, abs(y))
        * (1.0 - smoothstep(0.68, 0.74, abs(y)))
    )
    cross_horizontal = (
        (1.0 - smoothstep(0.022, 0.022 + antialias, abs(y)))
        * smoothstep(0.27, 0.33, abs(x))
        * (1.0 - smoothstep(0.68, 0.74, abs(x)))
    )
    reticle = clamp(
        outer_ring + inner_ring + cross_vertical + cross_horizontal
    )
    base = blend(base, (218.0, 226.0, 193.0), reticle * 0.88)

    slash_distance = abs(y + 0.58 * x - 0.02) / math.sqrt(1.0 + 0.58**2)
    slash_extent = max(abs(x) / 0.72, abs(y) / 0.55)
    slash = (
        1.0 - smoothstep(0.055, 0.055 + antialias, slash_distance)
    ) * (1.0 - smoothstep(0.92, 1.0, slash_extent))
    slash_glow = (
        1.0 - smoothstep(0.055, 0.17, slash_distance)
    ) * (1.0 - smoothstep(0.92, 1.0, slash_extent))
    base = blend(base, (205.0, 92.0, 26.0), slash_glow * 0.42)
    base = blend(base, (247.0, 144.0, 42.0), slash * 0.98)

    center = 1.0 - smoothstep(0.055, 0.055 + antialias, radius)
    base = blend(base, (255.0, 194.0, 76.0), center)

    highlight = clamp((0.18 - (x + y + 0.48)) / 0.75) * 0.12
    base = blend(base, (255.0, 255.0, 238.0), highlight)
    return (
        int(clamp(base[0], 0.0, 255.0)),
        int(clamp(base[1], 0.0, 255.0)),
        int(clamp(base[2], 0.0, 255.0)),
        int(alpha * 255.0 + 0.5),
    )


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def write_png(path: str, size: int) -> None:
    antialias = 2.0 / size
    rows = bytearray()
    for py in range(size):
        rows.append(0)
        y = 1.0 - (py + 0.5) * 2.0 / size
        for px in range(size):
            x = (px + 0.5) * 2.0 / size - 1.0
            rows.extend(pixel(x, y, antialias))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    encoded = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + png_chunk(b"IEND", b"")
    )
    with open(path, "wb") as output:
        output.write(encoded)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    for name, size in ICON_SIZES.items():
        write_png(os.path.join(args.output_dir, name), size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
