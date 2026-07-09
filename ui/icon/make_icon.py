#!/usr/bin/env python3
"""Generate Rewisp.icns — FINAL: tapered white wisp stroke on graphite squircle.
(User-selected 2026-07-08: 'wisp' concept, inverted colors.)
Pure CoreGraphics — no image assets, fully reproducible."""

import math
import subprocess
import tempfile
from pathlib import Path

import Quartz
from Foundation import NSURL

S = 1024
OUT = Path(__file__).parent


def draw():
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, S, S, 8, S * 4, cs,
                                       Quartz.kCGImageAlphaPremultipliedLast)

    # Apple icon grid: squircle inset ~10%, corner radius ~22.5%
    inset = S * 0.10
    radius = (S - 2 * inset) * 0.225
    rect = Quartz.CGRectMake(inset, inset, S - 2 * inset, S - 2 * inset)

    Quartz.CGContextSaveGState(ctx)
    Quartz.CGContextAddPath(ctx, Quartz.CGPathCreateWithRoundedRect(rect, radius, radius, None))
    Quartz.CGContextClip(ctx)

    grad = Quartz.CGGradientCreateWithColors(cs, [
        Quartz.CGColorCreate(cs, [0.165, 0.180, 0.253, 1.0]),  # top    #2A2E41
        Quartz.CGColorCreate(cs, [0.055, 0.063, 0.114, 1.0]),  # bottom #0E101D
    ], [0.0, 1.0])
    Quartz.CGContextDrawLinearGradient(ctx, grad,
                                       Quartz.CGPointMake(S / 2, S - inset),
                                       Quartz.CGPointMake(S / 2, inset), 0)

    # Wisp: flowing tapered stroke, ending in a bright memory point.
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    pts = 200
    prev = None
    for i in range(pts + 1):
        f = i / pts
        x = S * 0.20 + f * S * 0.56
        y = S * 0.50 + math.sin(f * math.pi * 2.2 + 0.4) * S * 0.115 * (1 - 0.40 * f)
        if prev:
            w = S * (0.052 - 0.028 * f)
            Quartz.CGContextSetRGBStrokeColor(ctx, 0.93, 0.95, 1.0, 0.96)
            Quartz.CGContextSetLineWidth(ctx, w)
            Quartz.CGContextBeginPath(ctx)
            Quartz.CGContextMoveToPoint(ctx, *prev)
            Quartz.CGContextAddLineToPoint(ctx, x, y)
            Quartz.CGContextStrokePath(ctx)
        prev = (x, y)

    ex, ey = prev
    d = S * 0.030
    Quartz.CGContextSetRGBFillColor(ctx, 1.0, 1.0, 1.0, 1.0)
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(ex - d, ey - d, d * 2, d * 2))

    Quartz.CGContextRestoreGState(ctx)
    return Quartz.CGBitmapContextCreateImage(ctx)


def save_png(image, path: Path):
    dest = Quartz.CGImageDestinationCreateWithURL(
        NSURL.fileURLWithPath_(str(path)), "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, image, None)
    Quartz.CGImageDestinationFinalize(dest)


def main():
    img = draw()
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "Rewisp.iconset"
        iconset.mkdir()
        master = Path(td) / "master.png"
        save_png(img, master)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
                subprocess.run(["sips", "-z", str(px), str(px), str(master),
                                "--out", str(iconset / name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset),
                        "-o", str(OUT / "Rewisp.icns")], check=True)
    save_png(img, OUT / "icon_preview.png")
    print("wrote Rewisp.icns + icon_preview.png")


if __name__ == "__main__":
    main()
