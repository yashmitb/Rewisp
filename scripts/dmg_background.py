"""Draw the DMG window background (dark, branded, with a drag arrow).

Uses Quartz via pyobjc — already a dependency, so no image library needed.
Output is a @2x PNG plus a 1x, which Finder picks between automatically.
"""

import sys

import CoreText
import Quartz

W, H = 660, 420           # window content size (points)


def draw(scale: int, out_path: str) -> None:
    w, h = W * scale, H * scale
    space = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, w, h, 8, 0, space,
        Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextScaleCTM(ctx, scale, scale)

    def rgb(r, g, b, a=1.0):
        return Quartz.CGColorCreateGenericRGB(r, g, b, a)

    # Background: deep navy with a soft violet glow up top (matches the site).
    Quartz.CGContextSetFillColorWithColor(ctx, rgb(0.043, 0.051, 0.086))
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, W, H))

    grad = Quartz.CGGradientCreateWithColors(
        space,
        [rgb(0.56, 0.64, 1.0, 0.20), rgb(0.56, 0.64, 1.0, 0.0)],
        [0.0, 1.0])
    Quartz.CGContextDrawRadialGradient(
        ctx, grad,
        Quartz.CGPointMake(W / 2, H + 40), 0,
        Quartz.CGPointMake(W / 2, H + 40), 340,
        Quartz.kCGGradientDrawsBeforeStartLocation)

    # Arrow between the two icons (icons sit at y≈250 in Finder's coordinates,
    # which are bottom-left origin — same as Quartz, so this lines up).
    ay = H - 250
    x0, x1 = 268.0, 392.0
    Quartz.CGContextSetStrokeColorWithColor(ctx, rgb(0.56, 0.64, 1.0, 0.55))
    Quartz.CGContextSetLineWidth(ctx, 3.0)
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    Quartz.CGContextBeginPath(ctx)
    Quartz.CGContextMoveToPoint(ctx, x0, ay)
    Quartz.CGContextAddLineToPoint(ctx, x1 - 12, ay)
    Quartz.CGContextStrokePath(ctx)
    # arrowhead
    Quartz.CGContextSetFillColorWithColor(ctx, rgb(0.56, 0.64, 1.0, 0.75))
    Quartz.CGContextBeginPath(ctx)
    Quartz.CGContextMoveToPoint(ctx, x1 + 4, ay)
    Quartz.CGContextAddLineToPoint(ctx, x1 - 16, ay + 10)
    Quartz.CGContextAddLineToPoint(ctx, x1 - 16, ay - 10)
    Quartz.CGContextClosePath(ctx)
    Quartz.CGContextFillPath(ctx)

    # Caption under the arrow.
    text = "Drag Rewisp into Applications"
    font = (CoreText.CTFontCreateWithName("SFProText-Semibold", 15, None)
            or CoreText.CTFontCreateWithName("Helvetica", 15, None))
    attrs = {
        CoreText.kCTFontAttributeName: font,
        CoreText.kCTForegroundColorAttributeName: rgb(0.72, 0.75, 0.83),
    }
    line = CoreText.CTLineCreateWithAttributedString(
        CoreText.CFAttributedStringCreate(None, text, attrs))
    bounds = CoreText.CTLineGetImageBounds(line, ctx)
    Quartz.CGContextSetTextPosition(
        ctx, (W - Quartz.CGRectGetWidth(bounds)) / 2, ay - 74)
    CoreText.CTLineDraw(line, ctx)

    img = Quartz.CGBitmapContextCreateImage(ctx)
    url = Quartz.CFURLCreateWithFileSystemPath(None, out_path, 0, False)
    dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, img, None)
    Quartz.CGImageDestinationFinalize(dest)


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "background"
    draw(1, f"{base}.png")
    draw(2, f"{base}@2x.png")
    print(f"✓ wrote {base}.png and {base}@2x.png ({W}x{H})")
