"""Draw the DMG window background: a white card holding both icons.

Uses Quartz + CoreText via pyobjc — already a dependency, so no image library.
Writes a 1x and a @2x PNG, which Finder picks between automatically.

Design constraint worth knowing before changing this: **Finder draws icon labels
in black**, whatever the background image is. The first version used a dark navy
background to match the site, which rendered "Applications" black-on-black and
unreadable. The light palette is not a style preference — it is the only thing
Finder's labels are legible against.

Second constraint: an icon's y position in Finder is its CENTRE, and its label
hangs roughly 75px below that. The caption has to clear it, or the two collide.
"""

import sys

import CoreText
import Quartz

W, H = 720, 480           # window content size (points)
ICON_Y = 205              # icon centres, measured from the TOP (Finder's origin)
ICON_L, ICON_R = 190, 530
CAPTION_TOP = 358         # below the card, which ends at y=312


def rounded_rect(x, yy, w, h, r):
    """Rounded-rect path, bottom-left origin (Quartz convention)."""
    p = Quartz.CGPathCreateMutable()
    Quartz.CGPathMoveToPoint(p, None, x + r, yy)
    Quartz.CGPathAddArcToPoint(p, None, x + w, yy, x + w, yy + h, r)
    Quartz.CGPathAddArcToPoint(p, None, x + w, yy + h, x, yy + h, r)
    Quartz.CGPathAddArcToPoint(p, None, x, yy + h, x, yy, r)
    Quartz.CGPathAddArcToPoint(p, None, x, yy, x + w, yy, r)
    Quartz.CGPathCloseSubpath(p)
    return p


def draw(scale: int, out_path: str) -> None:
    w, h = W * scale, H * scale
    space = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, w, h, 8, 0, space, Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextScaleCTM(ctx, scale, scale)

    def rgb(r, g, b, a=1.0):
        return Quartz.CGColorCreateGenericRGB(r, g, b, a)

    # Quartz is bottom-left origin, Finder is top-left. Convert once.
    def y(top):
        return H - top

    # ── field: soft lavender-grey wash ──
    grad = Quartz.CGGradientCreateWithColors(
        space,
        [rgb(0.906, 0.918, 0.957), rgb(0.847, 0.863, 0.925)],
        [0.0, 1.0])
    Quartz.CGContextDrawLinearGradient(
        ctx, grad, Quartz.CGPointMake(0, H), Quartz.CGPointMake(0, 0), 0)

    # ── the card the two icons sit on ──
    # Bottom edge clears the icon labels (which end near y=285) by ~27px, so the
    # panel never crops the words "Rewisp" and "Applications".
    card_top, card_bottom = 84, 312
    card = rounded_rect(56, y(card_bottom), W - 112, card_bottom - card_top, 22)
    Quartz.CGContextSaveGState(ctx)
    Quartz.CGContextSetShadowWithColor(
        ctx, Quartz.CGSizeMake(0, -7), 24, rgb(0.16, 0.18, 0.30, 0.16))
    Quartz.CGContextAddPath(ctx, card)
    Quartz.CGContextSetFillColorWithColor(ctx, rgb(1, 1, 1, 0.90))
    Quartz.CGContextFillPath(ctx)
    Quartz.CGContextRestoreGState(ctx)

    # Hairline edge so the card reads as a surface, not a blur.
    Quartz.CGContextAddPath(ctx, card)
    Quartz.CGContextSetStrokeColorWithColor(ctx, rgb(1, 1, 1, 0.9))
    Quartz.CGContextSetLineWidth(ctx, 1.0)
    Quartz.CGContextStrokePath(ctx)

    # ── arrow between the icons ──
    ay = y(ICON_Y)
    x0, x1 = ICON_L + 106, ICON_R - 102
    Quartz.CGContextSetStrokeColorWithColor(ctx, rgb(0.36, 0.41, 0.78, 0.5))
    Quartz.CGContextSetLineWidth(ctx, 5.0)
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    Quartz.CGContextBeginPath(ctx)
    Quartz.CGContextMoveToPoint(ctx, x0, ay)
    Quartz.CGContextAddLineToPoint(ctx, x1 - 18, ay)
    Quartz.CGContextStrokePath(ctx)

    Quartz.CGContextSetFillColorWithColor(ctx, rgb(0.36, 0.41, 0.78, 0.72))
    Quartz.CGContextBeginPath(ctx)
    Quartz.CGContextMoveToPoint(ctx, x1 + 6, ay)
    Quartz.CGContextAddLineToPoint(ctx, x1 - 20, ay + 13)
    Quartz.CGContextAddLineToPoint(ctx, x1 - 20, ay - 13)
    Quartz.CGContextClosePath(ctx)
    Quartz.CGContextFillPath(ctx)

    def text(s, size, face, colour, top):
        font = (CoreText.CTFontCreateWithName(face, size, None)
                or CoreText.CTFontCreateWithName("Helvetica", size, None))
        line = CoreText.CTLineCreateWithAttributedString(
            CoreText.CFAttributedStringCreate(None, s, {
                CoreText.kCTFontAttributeName: font,
                CoreText.kCTForegroundColorAttributeName: colour,
            }))
        bounds = CoreText.CTLineGetImageBounds(line, ctx)
        Quartz.CGContextSetTextPosition(
            ctx, (W - Quartz.CGRectGetWidth(bounds)) / 2, y(top))
        CoreText.CTLineDraw(line, ctx)

    # ── caption, well below the icon labels ──
    text("Drag Rewisp into your Applications folder",
         16.5, "SFProText-Semibold", rgb(0.15, 0.17, 0.25), CAPTION_TOP)
    text("Then open Rewisp from there, not from this window.",
         12.5, "SFProText-Regular", rgb(0.45, 0.48, 0.57), CAPTION_TOP + 27)

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
