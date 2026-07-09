#!/usr/bin/env python3
"""Render 4 icon concepts side by side -> icon_ideas.png"""

import math
import Quartz
from Foundation import NSURL

S = 512  # per-tile icon size
PAD = 40
CS = Quartz.CGColorSpaceCreateDeviceRGB()


def squircle(ctx, inset, radius):
    r = Quartz.CGRectMake(inset, inset, S - 2 * inset, S - 2 * inset)
    Quartz.CGContextAddPath(ctx, Quartz.CGPathCreateWithRoundedRect(r, radius, radius, None))


def bg_gradient(ctx, top, bottom):
    inset = S * 0.10
    radius = (S - 2 * inset) * 0.225
    Quartz.CGContextSaveGState(ctx)
    squircle(ctx, inset, radius)
    Quartz.CGContextClip(ctx)
    grad = Quartz.CGGradientCreateWithColors(CS, [
        Quartz.CGColorCreate(CS, list(top) + [1.0]),
        Quartz.CGColorCreate(CS, list(bottom) + [1.0]),
    ], [0.0, 1.0])
    Quartz.CGContextDrawLinearGradient(ctx, grad,
                                       Quartz.CGPointMake(S / 2, S - inset),
                                       Quartz.CGPointMake(S / 2, inset), 0)


DARK_TOP, DARK_BOT = (0.165, 0.180, 0.253), (0.055, 0.063, 0.114)


def concept_a(ctx):
    """Echo — concentric arcs radiating from a bright memory point."""
    bg_gradient(ctx, DARK_TOP, DARK_BOT)
    cx, cy = S * 0.40, S * 0.42
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    for i, (r, alpha, w) in enumerate([(S * 0.13, 0.95, S * 0.030),
                                       (S * 0.22, 0.55, S * 0.026),
                                       (S * 0.31, 0.28, S * 0.022)]):
        Quartz.CGContextSetRGBStrokeColor(ctx, 0.93, 0.95, 1.0, alpha)
        Quartz.CGContextSetLineWidth(ctx, w)
        Quartz.CGContextBeginPath(ctx)
        Quartz.CGContextAddArc(ctx, cx, cy, r, math.radians(-55), math.radians(75), 0)
        Quartz.CGContextStrokePath(ctx)
    d = S * 0.045
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(cx - d/2, cy - d/2, d, d))
    Quartz.CGContextRestoreGState(ctx)


def concept_b(ctx):
    """Recall — fading dot grid, one dot lit. A memory found among many."""
    bg_gradient(ctx, DARK_TOP, DARK_BOT)
    n = 4
    span = S * 0.52
    x0, y0 = (S - span) / 2, (S - span) / 2
    step = span / (n - 1)
    d = S * 0.055
    for row in range(n):
        for col in range(n):
            x, y = x0 + col * step, y0 + row * step
            # fade toward bottom-right; one dot is the "found" memory
            if (row, col) == (1, 2):
                continue
            alpha = 0.75 - 0.16 * ((row + col) / (2 * n - 2)) * 3
            alpha = max(alpha, 0.10)
            Quartz.CGContextSetRGBFillColor(ctx, 0.85, 0.88, 1.0, alpha)
            Quartz.CGContextFillEllipseInRect(
                ctx, Quartz.CGRectMake(x - d/2, y - d/2, d, d))
    # the lit memory: larger, bright, subtle ring
    x, y = x0 + 2 * step, y0 + 1 * step
    d2 = S * 0.085
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(x - d2/2, y - d2/2, d2, d2))
    Quartz.CGContextSetRGBStrokeColor(ctx, 1, 1, 1, 0.35)
    Quartz.CGContextSetLineWidth(ctx, S * 0.012)
    ring = S * 0.15
    Quartz.CGContextStrokeEllipseInRect(ctx, Quartz.CGRectMake(x - ring/2, y - ring/2, ring, ring))
    Quartz.CGContextRestoreGState(ctx)


def concept_c(ctx):
    """Monogram — geometric lowercase r, stem + arc, indigo-violet gradient."""
    bg_gradient(ctx, (0.29, 0.27, 0.60), (0.13, 0.11, 0.32))
    w = S * 0.075
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    Quartz.CGContextSetRGBStrokeColor(ctx, 1, 1, 1, 0.97)
    Quartz.CGContextSetLineWidth(ctx, w)
    # stem
    x = S * 0.40
    Quartz.CGContextBeginPath(ctx)
    Quartz.CGContextMoveToPoint(ctx, x, S * 0.68)
    Quartz.CGContextAddLineToPoint(ctx, x, S * 0.32)
    Quartz.CGContextStrokePath(ctx)
    # shoulder arc
    Quartz.CGContextBeginPath(ctx)
    Quartz.CGContextAddArc(ctx, x + S * 0.115, S * 0.545, S * 0.115,
                           math.radians(180), math.radians(20), 1)
    Quartz.CGContextStrokePath(ctx)
    # memory dot at the arc's end
    ex = x + S * 0.115 + S * 0.115 * math.cos(math.radians(20))
    ey = S * 0.545 + S * 0.115 * math.sin(math.radians(20))
    d = S * 0.035
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(ex - d, ey - d, d*2, d*2))
    Quartz.CGContextRestoreGState(ctx)


def concept_d(ctx):
    """Paper — light mode: warm off-white, single thin ink stroke wave (a wisp of text)."""
    bg_gradient(ctx, (0.97, 0.965, 0.95), (0.92, 0.915, 0.90))
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    Quartz.CGContextSetRGBStrokeColor(ctx, 0.10, 0.10, 0.12, 0.92)
    Quartz.CGContextSetLineWidth(ctx, S * 0.045)
    # sine-ish wisp: three flowing crests, like a signature underline
    Quartz.CGContextBeginPath(ctx)
    pts = 160
    for i in range(pts + 1):
        f = i / pts
        x = S * 0.22 + f * S * 0.52
        y = S * 0.50 + math.sin(f * math.pi * 2.2 + 0.4) * S * 0.11 * (1 - 0.45 * f)
        if i == 0:
            Quartz.CGContextMoveToPoint(ctx, x, y)
        else:
            Quartz.CGContextAddLineToPoint(ctx, x, y)
    Quartz.CGContextStrokePath(ctx)
    ex = S * 0.22 + S * 0.52
    ey = S * 0.50 + math.sin(math.pi * 2.2 + 0.4) * S * 0.11 * 0.55
    d = S * 0.028
    Quartz.CGContextSetRGBFillColor(ctx, 0.10, 0.10, 0.12, 1)
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(ex - d, ey - d, d*2, d*2))
    Quartz.CGContextRestoreGState(ctx)


def main():
    concepts = [concept_a, concept_b, concept_c, concept_d]
    W = S * len(concepts) + PAD * (len(concepts) + 1)
    H = S + 2 * PAD
    ctx = Quartz.CGBitmapContextCreate(None, W, H, 8, W * 4, CS,
                                       Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextSetRGBFillColor(ctx, 0.12, 0.12, 0.13, 1)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, W, H))
    for i, fn in enumerate(concepts):
        Quartz.CGContextSaveGState(ctx)
        Quartz.CGContextTranslateCTM(ctx, PAD + i * (S + PAD), PAD)
        fn(ctx)
        Quartz.CGContextRestoreGState(ctx)
    img = Quartz.CGBitmapContextCreateImage(ctx)
    url = NSURL.fileURLWithPath_("icon_ideas.png")
    dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, img, None)
    Quartz.CGImageDestinationFinalize(dest)
    print("wrote icon_ideas.png")


if __name__ == "__main__":
    main()
