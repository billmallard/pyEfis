import math

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtWidgets import *
from PyQt6.QtGui import *

#: Shared readout-panel design tokens.
#:
#: The HSI's integral readout panel (P5a) established the house look for a
#: value read off a moving background: a rounded container over a translucent
#: black fill, bordered in the foreground colour. P5c extends the same look to
#: the airspeed/altitude tape readout boxes, which previously used a solid
#: white-on-black rectangle with bracket "arms" and an opaque black triangle.
#: Every instrument that draws one goes through the two functions below, so the
#: HSI panel and the tape boxes cannot drift apart.
#:
#: The fill is deliberately translucent rather than solid: these boxes sit over
#: the SVS/attitude background, and a solid block reads as a hole punched in
#: the scene. 0.62 keeps a white value well above the WCAG 4.5:1 contrast floor
#: even over a fully-lit sky (see tests/instruments/test_readout_panel.py).
READOUT_FILL_ALPHA = 0.62
READOUT_BORDER_ALPHA = 0.85
#: Corner radius and border width, both as a fraction of the readout's font
#: size, so the panel scales with the instrument instead of with the screen.
#: This is the HSI's own token (its top_panel readout uses it directly against
#: `self.fontSize`) -- do not repoint the tape boxes at it, see
#: TAPE_READOUT_RADIUS_RATIO below.
READOUT_RADIUS_RATIO = 0.35
READOUT_PEN_RATIO = 0.06
#: Tape readout box (airspeed/altitude) corner radius, as a fraction of the
#: box's OWN base quantity: `font_height`, the fitted digit glyph height in
#: NumericalDisplay (panel height there is 1.20 * font_height). This is a
#: separate token from READOUT_RADIUS_RATIO on purpose (AER-386, Bill
#: 2026-08-27: "the roundedness of the airspeed and altitude boxes is too
#: much"): READOUT_RADIUS_RATIO is keyed to the HSI's `fontSize`, a different
#: base quantity, and the tape box is much shorter relative to its own font
#: than the HSI panel is to its own fontSize -- reusing 0.35 against
#: font_height ate ~29% of the tape box's height (near the geometric max
#: before QPainter clamps a rounded rect to a full stadium/pill -- confirmed
#: by rendering, see below) versus ~14.5% for the HSI's panel.
#:
#: Calibrated by rendering both at the sizes they occupy on a real PFD
#: (virtual_vfr.yaml's grid, at 1920x1080): the HSI top_panel panel there is
#: 950x950 (font_percent 0.05 -> fontSize 48 -> radius 48*0.35 = 16.8px,
#: 14.5% of its 115.52px panel height). Reusing that ABSOLUTE 16.8px on the
#: tape box (font_percent 0.25/0.24 -> font_height 22.0, panel height
#: 1.20*22.0 = 26.4px) exceeds half the panel height, so QPainter clamps it to
#: a full pill -- visually indistinguishable from the too-round original and
#: not a fix (rendered and compared to confirm). Matching the HSI's
#: *proportion* instead -- radius = 14.5% of panel height = 0.145 * 26.4 =
#: 3.84px -- reads as the same restrained, boxy corner as the HSI. As a
#: fraction of font_height that is 3.84 / 22.0 = 0.1745, rounded to 0.17
#: (3.74px at that font_height).
TAPE_READOUT_RADIUS_RATIO = 0.17


def readout_panel_pen_brush(border_color, pen_width=1.0,
                            fill_alpha=READOUT_FILL_ALPHA,
                            border_alpha=READOUT_BORDER_ALPHA):
    """Pen + brush for the shared rounded readout container.

    Returned rather than drawn so the QGraphicsScene-based readouts
    (NumericalDisplay) and the QPainter-based ones (HSI) share one definition
    of the look. `border_color` is anything QColor accepts.
    """
    border = QColor(border_color)
    border.setAlphaF(max(0.0, min(1.0, float(border_alpha))))
    fill = QColor(0, 0, 0)
    fill.setAlphaF(max(0.0, min(1.0, float(fill_alpha))))
    return QPen(border, max(1.0, float(pen_width))), QBrush(fill)


def draw_readout_panel(painter, rect, radius, border_color, pen_width=1.0,
                       fill_alpha=READOUT_FILL_ALPHA,
                       border_alpha=READOUT_BORDER_ALPHA):
    """Draw the shared rounded readout container into `rect` (QRectF-able).

    QPainter convenience wrapper over readout_panel_pen_brush(); leaves the
    pen/brush set so a caller can keep drawing dividers in the same style.
    """
    pen, brush = readout_panel_pen_brush(
        border_color, pen_width, fill_alpha, border_alpha)
    painter.setPen(pen)
    painter.setBrush(brush)
    painter.drawRoundedRect(QRectF(rect), radius, radius)
    return pen, brush


#: Shared static-element drop-shadow tokens (AER-392 / pyEfis#142).
#:
#: A soft drop shadow under a static instrument element (the HSI rose, the
#: readout panel, and -- once #140 lands -- the nav-source tab) reads as a
#: house depth treatment, same precedent as READOUT_RADIUS_RATIO/
#: TAPE_READOUT_RADIUS_RATIO above. Config-gated per widget (default OFF);
#: these tokens are only the shared LOOK, not the per-frame cost decision --
#: see drop_shadow_effect() and bake_blurred_silhouette() below for the two
#: zero-per-frame-cost ways to apply it.
#:
#: HARD CONSTRAINT: no per-frame gaussian blur. The HSI was ~24% of GIL time
#: in flight before its rose bake landed (#94); a QGraphicsEffect applied to
#: a live view undoes that. Both helpers below exist to bake the blur exactly
#: once, into a cached image, so a shadow costs one blit per frame like the
#: rose/overlay caches it sits beside.
SHADOW_COLOR = QColor(0, 0, 0)
SHADOW_ALPHA = 0.6
#: Blur radius as a fraction of the shadowed element's own characteristic
#: size (the HSI passes its own fontSize, the same base unit READOUT_*
#: above uses) -- so the shadow scales with the instrument, not the screen.
SHADOW_BLUR_RATIO = 0.12
#: A drop shadow implies a FIXED light source. Content that gets baked once
#: and then rotated per-frame (the HSI rose card turns with heading) must
#: not carry a directional offset, or the implied light appears to swing
#: with heading (AER-392 gotcha #1) -- a symmetric, zero-offset blur halo is
#: the only offset that is rotation-safe. Screen-fixed content (the readout
#: panel, the nav-source tab) is free to use a real offset if a later pass
#: wants one; today both offsets are 0 for a consistent house look.
SHADOW_OFFSET_X = 0.0
SHADOW_OFFSET_Y = 0.0
#: A Gaussian blur needs room past the shadowed shape's own edge to fully
#: resolve. Baking directly into a canvas sized to just the shape (or to the
#: shape's on-screen position with no margin) clips the falloff into a hard,
#: rectangular edge partway through the halo -- it reads as a rendering bug,
#: not a soft shadow (AER-392 gotcha #2). This is the margin, as a multiple
#: of the blur radius, reserved on every side: both for the bake canvas
#: itself (see bake_blurred_silhouette) and for callers deciding how much
#: on-screen clearance a shadow needs before it is safe to draw at all
#: (see the HSI's rose-radius reservation and its readout-panel margin cap).
SHADOW_CANVAS_PAD_RATIO = 3.0


def drop_shadow_effect(blur_radius, color=SHADOW_COLOR, alpha=SHADOW_ALPHA,
                       x_offset=SHADOW_OFFSET_X, y_offset=SHADOW_OFFSET_Y):
    """A configured QGraphicsDropShadowEffect (Option 2, AER-392): attach to
    a QGraphicsItem that lives in a scene baked ONCE and blitted every frame
    (e.g. the HSI's compass-disc background item, captured by its rose
    bake) so the blur is paid once, not per paintEvent.

    Do not attach this to an item in a scene that is rendered live every
    frame -- see the no-per-frame-blur constraint on the tokens above.
    """
    fill = QColor(color)
    fill.setAlphaF(max(0.0, min(1.0, float(alpha))))
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(max(0.0, float(blur_radius)))
    effect.setColor(fill)
    effect.setXOffset(x_offset)
    effect.setYOffset(y_offset)
    return effect


def bake_blurred_silhouette(width, height, paint_shape, blur_radius,
                            color=SHADOW_COLOR, alpha=SHADOW_ALPHA):
    """Bake a blurred, flat-colour silhouette of a shape into a QImage ONCE
    (Option 4, AER-392): for static screen-fixed geometry that is painted
    fresh every frame with a QPainter (the HSI's readout-panel/box shells,
    and -- once #140 lands -- the nav-source tab), so a soft shadow still
    costs zero per-frame blur work. The silhouette is colour- and
    content-independent, so one bake serves every value/state the shape's
    live content can take (AER-392 gotcha #3).

    `paint_shape(painter)` draws the OPAQUE shape at its normal (widget)
    position/size -- e.g. `painter.drawRoundedRect(rect, radius, radius)`.
    Only the painted coverage matters; this function flattens it to
    `color`/`alpha` and blurs it.

    Returns `(image, pad)`. `image` is sized `(width + 2*pad, height +
    2*pad)` -- the pad reserves room for the Gaussian to fully resolve
    before the canvas edge (SHADOW_CANVAS_PAD_RATIO; omitting it clips the
    falloff into a hard square edge, gotcha #2). Blit the result at
    `(-pad, -pad)` in the caller's own widget-sized target so the
    silhouette lines up with the shape as `paint_shape` drew it.
    """
    pad = int(math.ceil(max(0.0, float(blur_radius)) * SHADOW_CANVAS_PAD_RATIO))
    w, h = int(width) + 2 * pad, int(height) + 2 * pad

    shape = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    shape.fill(0)
    sp = QPainter(shape)
    sp.setRenderHint(QPainter.RenderHint.Antialiasing)
    sp.translate(pad, pad)
    paint_shape(sp)
    sp.end()

    # Flatten the shape's coverage (its alpha channel) to one flat shadow
    # colour -- SourceIn keeps only the destination fill where the source
    # (the shape we just painted) was opaque.
    silhouette = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    silhouette.fill(0)
    tp = QPainter(silhouette)
    tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    tp.drawImage(0, 0, shape)
    tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    fill = QColor(color)
    fill.setAlphaF(max(0.0, min(1.0, float(alpha))))
    tp.fillRect(0, 0, w, h, fill)
    tp.end()

    scene = QGraphicsScene(0, 0, w, h)
    item = scene.addPixmap(QPixmap.fromImage(silhouette))
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(blur_radius)
    blur.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(blur)

    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    op = QPainter(out)
    op.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(op, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
    op.end()
    return out, pad


def fit_to_mask(width,height,mask,font,units_mask=None, units_ratio=0.8, numeric=False):
    font_size = 100
    error = 100
    minerror = 100
    goal = 0.02
    count = 0
    while ( error > goal):
        count += 1
        text_font = QFont(font)
        text_font.setPointSizeF(font_size)
        fm = QFontMetricsF(text_font)
        text_width = fm.horizontalAdvance(mask)
        if numeric:
            text_height = fm.tightBoundingRect(mask).height()
        else:
            text_height = fm.boundingRect(mask).height()
        units_width = 0
        units_height = 0
        if units_mask:
            units_font = QFont(font)
            units_font.setPointSizeF(font_size * units_ratio)
            fmu = QFontMetricsF(units_font)
            units_width = fmu.horizontalAdvance(units_mask)
        hfactor = height / text_height
        wfactor = width / ( text_width + units_width)
        if hfactor < 1 and wfactor < 1:
            factor = min(hfactor, wfactor)
        elif hfactor > 1 and wfactor > 1:
            factor = max(hfactor,wfactor)
        elif hfactor < 1 and wfactor > 1:
            factor = hfactor
        else:
            factor = wfactor
        error = abs(factor - 1)
        if factor > 1:
            if error < minerror:
                minerror = error
            else:
                break
        font_size = font_size * factor
    return font_size * 0.98




#: strip-cache ceiling: an altimeter tape at 30k ft x typical pph runs
#: ~12 MB; anything past this falls back to per-frame scene rendering.
_EDGE_FADE_CACHE_BYTES = 32 * 1024 * 1024


def render_view_edge_faded(view, fade_percent):
    """Paint a QGraphicsView's visible scene into its viewport with an
    alpha fade over the top and bottom ``fade_percent`` of the height,
    so a scrolling tape melts in/out at its ends instead of clipping.

    Call INSTEAD of ``super().paintEvent(event)`` when the widget's
    ``edge_fade`` option is > 0; anchored overlays (pointer, readout
    boxes) are then painted by the caller on top, unfaded. The scene's
    alpha is multiplied by a vertical gradient
    (CompositionMode_DestinationIn) in an offscreen buffer, so whatever
    sits behind the tape -- SVS terrain included -- shows through the
    fade. (DestinationIn on the widget's own backing store would also
    erase what is painted behind the tape.)

    Perf (#93): the tape scenes are STATIC between rebuilds --
    resizeEvent replaces ``view.scene`` wholesale and values only
    scroll the view -- so the full strip is rendered ONCE into an image
    cached on the view (keyed on scene identity + geometry). Each frame
    then blits the visible slice (SmoothPixmapTransform keeps subpixel
    scrolling smooth) and fades only the two edge strips; the old
    full-viewport gradient fill was a no-op over the middle ~70%.
    Re-rendering the scene per frame was ~12% of all GIL time in the
    post-#89 flight profile. Falls back to the per-frame render when
    the view is scaled or the strip would exceed the cache ceiling.
    """
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import (QColor, QImage, QLinearGradient, QPainter)
    vp = view.viewport()
    w, h = vp.width(), vp.height()
    if w <= 0 or h <= 0:
        return
    f = max(0.0, min(45.0, float(fade_percent))) / 100.0

    scene = view.scene
    srect = scene.sceneRect()
    t = view.transform()
    plain = (abs(t.m11() - 1.0) < 1e-9 and abs(t.m22() - 1.0) < 1e-9
             and t.m12() == 0.0 and t.m21() == 0.0)
    sw = int(srect.width() + 0.5)
    sh = int(srect.height() + 0.5)

    strip = None
    if plain and 0 < sw * sh * 4 <= _EDGE_FADE_CACHE_BYTES:
        # The cache holds the scene OBJECT (not id()): a strong ref
        # keeps a replaced scene's identity from being recycled into a
        # false cache hit; the stale ref is dropped on the first paint
        # after a rebuild.
        key = (sw, sh, w, h,
               getattr(view, "foregroundOpacity", None),
               getattr(view, "backgroundOpacity", None))
        cached = getattr(view, "_edge_fade_strip", None)
        if (cached is not None and cached[0] is scene
                and cached[1] == key):
            strip = cached[2]
        else:
            strip = QImage(sw, sh, QImage.Format.Format_ARGB32_Premultiplied)
            strip.fill(0)
            sp = QPainter(strip)
            sp.setRenderHint(QPainter.RenderHint.Antialiasing)
            scene.render(sp, QRectF(0, 0, sw, sh), srect)
            sp.end()
            view._edge_fade_strip = (scene, key, strip)

    buf = getattr(view, "_edge_fade_buf", None)
    if buf is None or buf.width() != w or buf.height() != h:
        buf = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        view._edge_fade_buf = buf
    buf.fill(0)
    p = QPainter(buf)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    visible = view.mapToScene(vp.rect()).boundingRect()
    if strip is not None:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, w, h), strip,
                    QRectF(visible.x() - srect.x(),
                           visible.y() - srect.y(),
                           visible.width(), visible.height()))
    else:
        scene.render(p, QRectF(0, 0, w, h), visible)
    if f > 0.0:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(f, QColor(0, 0, 0, 255))
        grad.setColorAt(1.0 - f, QColor(0, 0, 0, 255))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn)
        fh = int(f * h + 1.0)
        p.fillRect(0, 0, w, fh, grad)
        p.fillRect(0, h - fh, w, fh, grad)
    p.end()
    out = QPainter(vp)
    out.drawImage(0, 0, buf)
    out.end()
