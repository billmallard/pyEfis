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
#: Corner radius of a rounded readout container, as a fraction of the
#: container's OWN panel height -- so every readout box in the house style gets
#: the same corner from ONE number, with no per-widget arithmetic: the HSI's
#: HDG|MAG|CRS panel, the airspeed/altitude tape boxes, the airspeed TAS box,
#: and any future rounded container (the nav-source tab, #143). Keyed to panel
#: HEIGHT -- not to a font size, and not to a panel-height multiplier -- on
#: purpose (AER-386/AER-413; Bill 2026-08-27: "we will likely be using it some
#: more").
#:
#: Why height, and why 0.145 -- the derivation is kept because it is the reason
#: absolute-pixel matching fails. Calibrated by rendering both containers at
#: the sizes they occupy on a real PFD (virtual_vfr.yaml's grid, at 1920x1080):
#: the HSI top_panel panel there is 950x950 (font_percent 0.05 -> fontSize 48),
#: and its sectioned readout panel is 115.52px tall with a 16.8px corner --
#: 16.8 / 115.52 = 0.145 of its own height. Reusing that ABSOLUTE 16.8px on the
#: much shorter tape box (font_percent 0.25/0.24 -> font_height 22.0, panel
#: height 1.20 * 22.0 = 26.4px) exceeds half the panel height, so QPainter
#: clamps it to a full pill -- visually indistinguishable from the too-round
#: original and not a fix (rendered and compared to confirm). Matching the
#: HSI's *proportion* instead -- 0.145 * 26.4 = 3.84px -- reads as the same
#: restrained, boxy corner as the HSI.
#:
#: The earlier TAPE_READOUT_RADIUS_RATIO folded the 1.20 panel-height
#: multiplier (_READOUT_PANEL_H in NumericalDisplay) into the token: 0.145 *
#: 1.20 = 0.174 against font_height. Keying to panel height directly means a
#: change to that multiplier moves the panel and its corner together instead of
#: silently breaking the HSI match -- pinned by test_readout_panel.py (AER-413).
READOUT_RADIUS_RATIO = 0.145
#: Border width as a fraction of the readout's font size.
READOUT_PEN_RATIO = 0.06


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


#: WCAG 2.x contrast floor for text/label colour derived from a bright,
#: config-selectable fill (AER-473 / pyEfis#147). Named so a caller can cite
#: the standard being met rather than a bare number, and so the target can be
#: tightened/loosened in one place.
SOURCE_LABEL_MIN_CONTRAST = 4.5


def _srgb_to_linear(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb):
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg_color, bg_color):
    """WCAG 2.x contrast ratio between two QColor-able values."""
    fg, bg = QColor(fg_color), QColor(bg_color)
    l1 = _relative_luminance((fg.red(), fg.green(), fg.blue()))
    l2 = _relative_luminance((bg.red(), bg.green(), bg.blue()))
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def darken_to_contrast(color, target_ratio=SOURCE_LABEL_MIN_CONTRAST, step=0.01):
    """Darken `color` (same hue/saturation) until its contrast against its
    OWN original value clears `target_ratio`, without changing hue.

    Built for a label drawn in a darkened tint of the same bright fill it
    sits on (the nav-source tab, AER-473): the fill IS the background, so
    darkening always increases contrast monotonically down to black. Walks
    HSV value down in `step` increments rather than solving analytically --
    the contrast formula isn't trivially invertible through sRGB gamma, and a
    coarse deterministic walk is easier to reason about than a solver here.
    """
    bg = QColor(color)
    h, s, v, a = bg.getHsvF()
    vv = v
    while vv > 0.0:
        candidate = QColor.fromHsvF(h, s, vv, a)
        if contrast_ratio(candidate, bg) >= target_ratio:
            return candidate
        vv -= step
    return QColor.fromHsvF(h, s, 0.0, a)


#: Shared static-element drop-shadow tokens (AER-392 / pyEfis#142).
#:
#: A soft drop shadow under a static instrument element (the HSI rose, the
#: readout panel, and -- once #140 lands -- the nav-source tab) reads as a
#: house depth treatment, same precedent as READOUT_RADIUS_RATIO above.
#: Config-gated per widget (default OFF);
#: these tokens are only the shared LOOK, not the per-frame cost decision --
#: see bake_blurred_silhouette() below for how it is applied without paying
#: per-frame blur cost.
#:
#: HARD CONSTRAINT: no per-frame gaussian blur. The HSI was ~24% of GIL time
#: in flight before its rose bake landed (#94); a QGraphicsEffect applied to
#: a live view undoes that. bake_blurred_silhouette() exists to bake the blur
#: exactly once, into a cached image, so a shadow costs one blit per frame
#: like the rose/overlay caches it sits beside. (A raw
#: QGraphicsDropShadowEffect on a scene item -- Option 2, AER-392 -- was
#: used for the HSI rose disc until AER-439: Qt's effect draws the item's
#: own source back on top of an UNPUNCHED blurred halo, so it tints any
#: translucent item with its own shadow the same way the pre-AER-415
#: bake_blurred_silhouette did, and exposes no punch-out knob to fix that.
#: bake_blurred_silhouette is the only supported mechanism now -- it already
#: punches its own shape back out (see AER-415 below).)
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
#: the only offset that is rotation-safe. bake_blurred_silhouette() has no
#: offset parameter for this reason: every current consumer (the rose, the
#: readout panel, the tape boxes) wants the same centred halo.
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
    `color`/`alpha`, blurs it, then punches `paint_shape`'s own coverage
    back OUT of the blurred result (AER-415) -- the interior is zero, and
    only the falloff that extends past the shape's edge survives. Without
    this, the halo is a solid filled silhouette under the shape's own
    footprint, and a caller that blits it under a translucent fill (e.g.
    the readout panel's `READOUT_FILL_ALPHA`) gets that solid fill reading
    straight through, tinting the whole interior instead of just its edge.

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

    # Punch the original opaque shape back out of its own blurred halo
    # (AER-415): the blur above smears the FULL filled silhouette outward,
    # so without this the baked image still carries a solid, flat-colour
    # fill everywhere the shape itself covers. Blitted under a panel whose
    # own fill is translucent by design (READOUT_FILL_ALPHA), that filled
    # interior reads straight through and tints the whole panel body, not
    # just the edge falloff. DestinationOut with the SAME path at the SAME
    # position removes exactly the shape's own coverage, leaving only the
    # soft falloff that extends past its edge.
    punch = QPainter(out)
    punch.setRenderHint(QPainter.RenderHint.Antialiasing)
    punch.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    punch.translate(pad, pad)
    paint_shape(punch)
    punch.end()

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
