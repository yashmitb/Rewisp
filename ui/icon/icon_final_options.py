#!/usr/bin/env python3
"""Final round: polished Recall (dark), polished Wisp (paper), and a hybrid -> icon_final.png"""

import math
import Quartz
from Foundation import NSURL

S = 512
PAD = 40
CS = Quartz.CGColorSpaceCreateDeviceRGB()


def bg(ctx, top, bottom):
    inset = S * 0.10
    radius = (S - 2 * inset) * 0.225
    r = Quartz.CGRectMake(inset, inset, S - 2 * inset, S - 2 * inset)
    Quartz.CGContextSaveGState(ctx)
    Quartz.CGContextAddPath(ctx, Quartz.CGPathCreateWithRoundedRect(r, radius, radius, None))
    Quartz.CGContextClip(ctx)
    grad = Quartz.CGGradientCreateWithColors(CS, [
        Quartz.CGColorCreate(CS, list(top) + [1.0]),
        Quartz.CGColorCreate(CS, list(bottom) + [1.0]),
    ], [0.0, 1.0])
    Quartz.CGContextDrawLinearGradient(ctx, grad,
                                       Quartz.CGPointMake(S / 2, S - inset),
                                       Quartz.CGPointMake(S / 2, inset), 0)


def dot_grid(ctx, ink, lit_pos=(1, 2), n=4):
    """Shared recall glyph: n x n dots, one lit with a ring."""
    span = S * 0.50
    x0, y0 = (S - span) / 2, (S - span) / 2
    step = span / (n - 1)
    d = S * 0.052
    for row in range(n):
        for col in range(n):
            if (row, col) == lit_pos:
                continue
            x, y = x0 + col * step, y0 + row * step
            # gentle radial fade away from the lit dot
            dist = math.hypot(row - lit_pos[0], col - lit_pos[1])
            alpha = max(0.62 - 0.14 * dist, 0.14)
            Quartz.CGContextSetRGBFillColor(ctx, *ink, alpha)
            Quartz.CGContextFillEllipseInRect(
                ctx, Quartz.CGRectMake(x - d/2, y - d/2, d, d))
    x, y = x0 + lit_pos[1] * step, y0 + lit_pos[0] * step
    d2 = S * 0.082
    Quartz.CGContextSetRGBFillColor(ctx, *ink, 1.0)
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(x - d2/2, y - d2/2, d2, d2))
    ring = S * 0.145
    Quartz.CGContextSetRGBStrokeColor(ctx, *ink, 0.32)
    Quartz.CGContextSetLineWidth(ctx, S * 0.011)
    Quartz.CGContextStrokeEllipseInRect(ctx, Quartz.CGRectMake(x - ring/2, y - ring/2, ring, ring))


def recall_dark(ctx):
    bg(ctx, (0.165, 0.180, 0.253), (0.055, 0.063, 0.114))
    # faint glow behind lit dot
    glow = Quartz.CGGradientCreateWithColors(CS, [
        Quartz.CGColorCreate(CS, [0.7, 0.75, 1.0, 0.18]),
        Quartz.CGColorCreate(CS, [0.7, 0.75, 1.0, 0.0]),
    ], [0.0, 1.0])
    span = S * 0.50
    x0, y0 = (S - span) / 2, (S - span) / 2
    step = span / 3
    gx, gy = x0 + 2 * step, y0 + 1 * step
    Quartz.CGContextDrawRadialGradient(ctx, glow, Quartz.CGPointMake(gx, gy), 0,
                                       Quartz.CGPointMake(gx, gy), S * 0.22, 0)
    dot_grid(ctx, (0.88, 0.90, 1.0))
    Quartz.CGContextRestoreGState(ctx)


def wisp_paper(ctx):
    bg(ctx, (0.97, 0.965, 0.95), (0.915, 0.91, 0.895))
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    ink = (0.10, 0.10, 0.12)
    # tapered flowing stroke, calligraphic: segments with shrinking width
    pts = 200
    Quartz.CGContextSetRGBStrokeColor(ctx, *ink, 0.94)
    prev = None
    for i in range(pts + 1):
        f = i / pts
        x = S * 0.20 + f * S * 0.56
        y = S * 0.50 + math.sin(f * math.pi * 2.2 + 0.4) * S * 0.115 * (1 - 0.40 * f)
        if prev:
            w = S * (0.052 - 0.028 * f)
            Quartz.CGContextSetLineWidth(ctx, w)
            Quartz.CGContextBeginPath(ctx)
            Quartz.CGContextMoveToPoint(ctx, *prev)
            Quartz.CGContextAddLineToPoint(ctx, x, y)
            Quartz.CGContextStrokePath(ctx)
        prev = (x, y)
    ex, ey = prev
    d = S * 0.030
    Quartz.CGContextSetRGBFillColor(ctx, *ink, 1)
    Quartz.CGContextFillEllipseInRect(ctx, Quartz.CGRectMake(ex - d, ey - d, d*2, d*2))
    Quartz.CGContextRestoreGState(ctx)


def recall_paper(ctx):
    """Hybrid: recall dot grid in ink on warm paper."""
    bg(ctx, (0.97, 0.965, 0.95), (0.915, 0.91, 0.895))
    dot_grid(ctx, (0.10, 0.10, 0.12))
    Quartz.CGContextRestoreGState(ctx)


def main():
    concepts = [recall_dark, wisp_paper, recall_paper]
    W = S * len(concepts) + PAD * (len(concepts) + 1)
    H = S + 2 * PAD
    ctx = Quartz.CGBitmapContextCreate(None, W, H, 8, W * 4, CS,
                                       Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextSetRGBFillColor(ctx, 0.55, 0.55, 0.57, 1)  # neutral gray, judge both themes
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, W, H))
    for i, fn in enumerate(concepts):
        Quartz.CGContextSaveGState(ctx)
        Quartz.CGContextTranslateCTM(ctx, PAD + i * (S + PAD), PAD)
        fn(ctx)
        Quartz.CGContextRestoreGState(ctx)
    img = Quartz.CGBitmapContextCreateImage(ctx)
    dest = Quartz.CGImageDestinationCreateWithURL(
        NSURL.fileURLWithPath_("icon_final.png"), "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, img, None)
    Quartz.CGImageDestinationFinalize(dest)
    print("wrote icon_final.png")


if __name__ == "__main__":
    main()
