from PyQt6.QtWidgets import *
from PyQt6.QtGui import *

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




def render_view_edge_faded(view, fade_percent):
    """Paint a QGraphicsView's visible scene into its viewport with an
    alpha fade over the top and bottom ``fade_percent`` of the height,
    so a scrolling tape melts in/out at its ends instead of clipping.

    Call INSTEAD of ``super().paintEvent(event)`` when the widget's
    ``edge_fade`` option is > 0; anchored overlays (pointer, readout
    boxes) are then painted by the caller on top, unfaded. The scene is
    rendered into a transparent image and its alpha multiplied by a
    vertical gradient (CompositionMode_DestinationIn), so whatever sits
    behind the tape -- SVS terrain included -- shows through the fade.
    """
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import (QColor, QImage, QLinearGradient, QPainter)
    vp = view.viewport()
    if vp.width() <= 0 or vp.height() <= 0:
        return
    f = max(0.0, min(45.0, float(fade_percent))) / 100.0
    img = QImage(vp.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.scene.render(
        p, QRectF(0, 0, img.width(), img.height()),
        view.mapToScene(vp.rect()).boundingRect())
    grad = QLinearGradient(0, 0, 0, img.height())
    grad.setColorAt(0.0, QColor(0, 0, 0, 0))
    grad.setColorAt(f, QColor(0, 0, 0, 255))
    grad.setColorAt(1.0 - f, QColor(0, 0, 0, 255))
    grad.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.fillRect(img.rect(), grad)
    p.end()
    out = QPainter(vp)
    out.drawImage(0, 0, img)
    out.end()
