#  SPDX-License-Identifier: GPL-2.0-or-later
"""Navigation Display (ND) mode for the moving map (G11a, billmallard/pyEfis#134).

EXPANDED MAP: the transport-category ND idiom built to the spec posted on
#134 (issuecomment-5552767516) as amended by Bill's G11 rulings (2026-11-07):

- a compass arc centred on ownship, track-up, ownship at ``h * 0.82`` (the
  HSI arc's ``own_y``), the selected range reaching the arc;
- corner data blocks, only the fields the 737 material lists AND the bus
  carries (see ``top_left`` / ``top_right`` / ``bottom_left``);
- a screen-fixed vertical deviation scale at the right edge driven by
  ``GSI``/``GSV``, the HSI's own glideslope keys, so the HSI needle and this
  scale always agree on whether vertical guidance is present;
- no lateral deviation scale (ruling 1: neither the 737 nor Garmin AXIS
  puts one on the map);
- 737 colours on these new elements only (ruling 2): the map's own layers
  and ownship keep their palette.

Not drawn, because nothing on the bus carries them: the bottom-left VOR1 /
FMC-source line, the bottom-centre RNP/ANP block, the bottom-right VOR2
block, the VNAV digital deviation readout (it is in feet; ``GSI`` is a
normalised deviation) and the RNP band. CTR MAP and the configurator twin
are G11b.

The model functions read through ``read(key)`` -> ``(value, old, bad, fail)``
or None for a key the gateway does not define, so tests assert what is drawn
without scraping pixels (the ``nav_status`` pattern).
"""

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QPolygonF

import pyavtools.fix as fix

#: ``nd_mode`` values, in ``nd_mode_key`` index order. Append only: the index
#: is what a button writes, so G11b's "ctr" goes on the end.
ND_MODES = ("off", "expanded")

#: ownship screen height in EXPANDED, as a fraction of the map height -- the
#: HSI arc's ``own_y = h * 0.82`` (hsi/__init__.py ``_arc_params``).
EXPANDED_OWN_Y_FRAC = 0.82
#: widest half-sector the compass arc draws, the HSI arc's ``ARC_HALF_DEG``.
ARC_HALF_DEG = 60.0
#: narrowest: on a tall or narrow panel the range radius shrinks before the
#: sector drops below this, so the arc never thins to a sliver at the top.
ARC_MIN_HALF_DEG = 40.0

# 737 ND colour code (#134 spec section 4), new ND elements only.
WHITE = QColor("#ffffff")      # status, scales
MAGENTA = QColor("#ff00ff")    # active / fly-to
CYAN = QColor("#00ffff")       # selected map options
RED = QColor("#ff0000")        # failed field, warning flag
GREY = QColor("#808080")       # bad / stale (the nav_status convention)

FAIL_TEXT = "XXX"
BAD_TIME = "--:--"

#: FIX keys the ND reads beyond what the map already subscribes to.
ND_KEYS = ("GS", "TAS", "WINDDIR", "WINDSPD", "FPLSTATE", "FPLPHASE",
           "WPNAME", "WPDIS", "WPETE", "GSI", "GSV")


def normalize_mode(mode):
    """``nd_mode`` as one of ND_MODES; anything unknown reads as ``off``."""
    mode = str(mode or "off").strip().lower()
    return mode if mode in ND_MODES else "off"


def font_px(w, h):
    """Data-block text size: the map's banner size (``_ui_metrics``)."""
    return max(11, int(min(w, h) * 0.035))


def status_chip_height(w):
    """Height of the map's top-left range chip (paintEvent), so the side
    blocks start below its row instead of under it."""
    return max(9, int(w * 0.03)) + 6


def arc_reach(w, h):
    """How far either side of centre the arc may reach: inside the panel,
    and clear of the vertical deviation scale at the right edge."""
    fs = font_px(w, h)
    return max(1.0, min(0.96 * w / 2.0,
                        vdev_geometry(w, h)["x"] - fs - w / 2.0))


def expanded_geometry(w, h):
    """EXPANDED screen geometry. ``own_y`` is the ownship anchor, ``r`` the
    compass-arc radius -- the selected range in px, so a feature on the arc
    is exactly ``range_nm`` away -- ``apex`` the arc's top, ``half`` the
    half-sector it spans, and the TRK box sits ``box_h`` tall over the apex
    with the lubber triangle in the ``fs * 0.5`` between them.

    On a landscape panel the arc reaches up to just under the TRK box at the
    top edge and spans ARC_HALF_DEG. On a tall or narrow one that radius
    would leave only a sliver of arc between the top corner blocks, so the
    radius shrinks until the arc spans ARC_MIN_HALF_DEG, and the TRK box
    follows the apex down."""
    fs = font_px(w, h)
    own_y = h * EXPANDED_OWN_Y_FRAC
    box_h = fs * 1.5
    reach = arc_reach(w, h)
    r = own_y - (4.0 + box_h + fs * 0.5)
    r = max(1.0, min(r, reach / math.sin(math.radians(ARC_MIN_HALF_DEG))))
    half = ARC_HALF_DEG if reach >= r else min(
        ARC_HALF_DEG, math.degrees(math.asin(reach / r)))
    return {"fs": fs, "own_y": own_y, "r": r, "apex": own_y - r,
            "box_h": box_h, "half": half}


def vdev_geometry(w, h):
    """The vertical deviation scale: x of its centre line, y of its centre
    (zero deviation) and the px for full-scale deviation (``GSI`` = 1)."""
    fs = font_px(w, h)
    return {"x": w - fs * 1.5, "y0": h * 0.5, "half": h * 0.18,
            "fs": fs}


# --- model ---------------------------------------------------------------

def _fmt_int(v):
    return "%d" % int(round(v))


def _fmt_deg(v):
    return "%03d" % (int(round(v)) % 360 or 360)


def _field(read, key, fmt):
    """One numeric field as ``(text, colour)``, or None when the key is
    absent: fail -> red XXX, bad/old -> grey, otherwise white."""
    r = read(key)
    if r is None:
        return None
    value, old, bad, fail = r
    if fail:
        return (FAIL_TEXT, RED)
    try:
        text = fmt(float(value))
    except (TypeError, ValueError):
        return (FAIL_TEXT, RED)
    return (text, GREY if (old or bad) else WHITE)


def top_left(read):
    """GS / TAS on the first line, wind direction / speed on the second, and
    the wind arrow's from-direction (magnetic, as ``WINDDIR``) or None when
    either wind field is not good."""
    lines = []
    speeds = []
    for label, key in (("GS", "GS"), ("TAS", "TAS")):
        f = _field(read, key, _fmt_int)
        if f is not None:
            speeds += [(label, WHITE), f]
    if speeds:
        lines.append(speeds)
    wdir = _field(read, "WINDDIR", _fmt_deg)
    wspd = _field(read, "WINDSPD", _fmt_int)
    arrow = None
    if wdir is not None and wspd is not None:
        if FAIL_TEXT in (wdir[0], wspd[0]):
            lines.append([(FAIL_TEXT, RED)])
        elif GREY in (wdir[1], wspd[1]):
            lines.append([("%s°/%s" % (wdir[0], wspd[0]), GREY)])
        else:
            lines.append([("%s°/%s" % (wdir[0], wspd[0]), WHITE)])
            arrow = float(read("WINDDIR")[0])
    return lines, arrow


def eta_text(ete_s, now=None):
    """ETA as the 737 writes it, UTC ``HHMM.Mz`` (FP7: computed on the
    display as now + ``WPETE``; the bus carries no ETA)."""
    t = (time.time() if now is None else now) + float(ete_s)
    tm = time.gmtime(t)
    tenths = int((tm.tm_sec / 60.0) * 10.0)
    return "%02d%02d.%dz" % (tm.tm_hour, tm.tm_min, tenths)


def top_right(read, now=None):
    """Active waypoint block: ident (magenta), ETA, distance (white), per the
    engine's published rules on #134 (FP7, issuecomment-5985422727):

    - drawn only while ``FPLSTATE`` != 0 (no plan publishes 0 / 0.0 / "");
    - ``FPLPHASE`` VECTORS: ETA and distance blank (the engine writes 0);
    - ``fail`` on ``WPDIS``/``WPETE``: that field red XXX (position lost);
    - ``bad`` on ``WPDIS``: grey; ``bad`` on ``WPETE``: ETA ``--:--``;
    - ``old`` on ``FPLSTATE``: the whole block grey.

    Returns a list of lines, each ``[(text, colour)]``; empty = no block."""
    st = read("FPLSTATE")
    if st is None or read("WPNAME") is None:
        return []
    try:
        state = int(st[0] or 0)
    except (TypeError, ValueError):
        state = 0
    if state == 0:
        return []
    stale = bool(st[1])
    ident = read("WPNAME")[0]
    ident = ident.strip() if isinstance(ident, str) else ""
    lines = [[(ident, MAGENTA)]] if ident else [[("", MAGENTA)]]
    ph = read("FPLPHASE")
    phase = ph[0].strip() if ph is not None and isinstance(ph[0], str) else ""
    if phase != "VECTORS":
        ete = read("WPETE")
        if ete is not None:
            if ete[3]:
                lines.append([(FAIL_TEXT, RED)])
            elif ete[2]:
                lines.append([(BAD_TIME, GREY)])
            else:
                try:
                    lines.append([(eta_text(ete[0], now), WHITE)])
                except (TypeError, ValueError):
                    lines.append([(FAIL_TEXT, RED)])
        dis = _field(read, "WPDIS",
                     lambda v: ("%.1f" % v) if v < 100.0 else "%d" % round(v))
        if dis is not None:
            lines.append([dis] if dis[0] == FAIL_TEXT
                         else [dis, ("NM", dis[1])])
    if stale:
        lines = [[(t, GREY) for t, _ in line] for line in lines]
    return lines


#: (map layer id, 737 option label) for the bottom-left option list. WXR
#: has no layer on this map; it is not listed.
OPTION_LABELS = (("airports", "ARPT"), ("fixes", "WPT"), ("navaids", "STA"))


def bottom_left(enabled_layers):
    """The selected map options, one per line, cyan."""
    return [[(label, CYAN)] for lid, label in OPTION_LABELS
            if lid in enabled_layers]


def vdev(read):
    """The vertical deviation scale's state, or None when it is not drawn:
    no ``GSI`` key, or ``GSV`` published and < 0.5 (no glideslope/glidepath,
    e.g. a VOR). Mirrors the HSI's rules exactly: an absent ``GSV`` leaves
    the scale up on ``GSI``'s own quality (an older gateway); the pointer is
    hidden on old/bad/fail; the red GS flag shows only when ``GSV`` says a
    glidepath is present and ``GSI`` is bad or failed.

    ``pointer`` is ``GSI`` clamped to the scale's +/-1 (pegged), or None."""
    gsi = read("GSI")
    if gsi is None:
        return None
    gsv = read("GSV")
    gsv_v = None
    if gsv is not None:
        try:
            gsv_v = float(gsv[0])
        except (TypeError, ValueError):
            gsv_v = 0.0
        if gsv_v < 0.5:
            return None
    value, old, bad, fail = gsi
    pointer = None
    if not (old or bad or fail):
        try:
            pointer = max(-1.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            pointer = None
    flag = gsv_v is not None and bool(bad or fail)
    return {"pointer": pointer, "flag": flag}


def vdev_pointer_y(g, pointer):
    """Screen y of the pointer: up for positive ``GSI``, the HSI's sign
    (``gy = gy0 - GSI * range``), so the two instruments agree."""
    return g["y0"] - pointer * g["half"]


# --- widget glue ---------------------------------------------------------

class Reader:
    """``read(key)`` over the live FIX database, looking each key up once.
    A key the gateway does not define reads as None for the life of the
    widget (construct-never-raises)."""

    def __init__(self):
        self._items = {}

    def __call__(self, key):
        if key not in self._items:
            try:
                self._items[key] = fix.db.get_item(key)
            except KeyError:
                self._items[key] = None
        item = self._items[key]
        if item is None:
            return None
        return item.value, item.old, item.bad, item.fail


def enabled_layers(widget):
    return {layer.id for layer in getattr(widget, "_layers", [])
            if layer.enabled}


def signature(widget, read):
    """Everything the ND draws from the bus, as a hashable tuple. The map's
    frame clock repaints only when its pose key changes; adding this keeps a
    moving GSI or a new waypoint from waiting for the aircraft to move."""
    tl, arrow = top_left(read)
    vd = vdev(read)
    return (repr(tl), None if arrow is None else round(arrow),
            repr(top_right(read)), tuple(sorted(enabled_layers(widget))),
            None if vd is None else (
                None if vd["pointer"] is None else round(vd["pointer"], 3),
                vd["flag"]))


# --- painting ------------------------------------------------------------

def _font(family, px, bold=False):
    f = QFont(family)
    f.setPixelSize(max(1, int(px)))
    f.setBold(bold)
    return f


def _draw_lines(p, lines, x, y, lh, align_right=False, right=None):
    """Draw ``lines`` of ``(text, colour)`` runs from ``(x, y)`` down, left
    aligned at x, or right aligned at ``right``."""
    fm = p.fontMetrics()
    space = fm.horizontalAdvance(" ")
    for line in lines:
        runs = [(t, c) for t, c in line if t]
        width = sum(fm.horizontalAdvance(t) for t, _ in runs) \
            + space * max(0, len(runs) - 1)
        cx = (right - width) if align_right else x
        for text, col in runs:
            p.setPen(QPen(col))
            p.drawText(QPointF(cx, y + fm.ascent()), text)
            cx += fm.horizontalAdvance(text) + space
        y += lh
    return y


def paint(widget, p, x, read, now=None):
    """Paint the EXPANDED overlay over the map layers and ownship. *x* is the
    frame's MapTransform, built with ``range_px`` = the arc radius."""
    w, h = float(x.w), float(x.h)
    g = expanded_geometry(w, h)
    fs = g["fs"]
    family = x.font_family
    osp = x.to_screen(widget._lat, widget._lon)
    r = x.nm_to_px(x.range_nm)          # == g["r"]: range_px is the arc
    up = math.degrees(x.rot)            # bearing at the top of the screen
    half = g["half"]
    lw = max(1.5, w * 0.003)

    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Compass arc: the circle at the selected range, 5 deg ticks, longer
    # every 10, a numeral every 30 (tens of degrees, 737 style).
    rect = QRectF(osp.x() - r, osp.y() - r, 2 * r, 2 * r)
    path = QPainterPath()
    path.arcMoveTo(rect, 90.0 + half)
    path.arcTo(rect, 90.0 + half, -2.0 * half)
    tick = fs * 0.6
    numerals = []
    first = int(math.ceil((up - half) / 5.0)) * 5
    for b in range(first, int(math.floor(up + half)) + 1, 5):
        rel = math.radians(b - up)
        sx, sy = math.sin(rel), -math.cos(rel)
        tl = tick if b % 10 == 0 else tick * 0.5
        path.moveTo(osp.x() + r * sx, osp.y() + r * sy)
        path.lineTo(osp.x() + (r - tl) * sx, osp.y() + (r - tl) * sy)
        if b % 30 == 0:
            rr = r - tick - fs * 0.7
            numerals.append((osp.x() + rr * sx, osp.y() + rr * sy,
                             "%d" % ((b % 360) // 10)))
    pen = QPen(WHITE, lw)
    p.setPen(pen)
    p.drawPath(path)
    p.setFont(_font(family, fs))
    for nx, ny, label in numerals:
        p.drawText(QRectF(nx - fs * 1.5, ny - fs * 0.7, fs * 3, fs * 1.4),
                   Qt.AlignmentFlag.AlignCenter, label)

    # TRK box at the top centre with the lubber triangle under it.
    trk_stale = widget._old.get("TRACKM", True)
    col = GREY if trk_stale else WHITE
    bf = _font(family, fs, bold=True)
    p.setFont(bf)
    fm = p.fontMetrics()
    sp = fm.horizontalAdvance(" ")
    runs = [("TRK", fs * 0.8), (_fmt_deg(widget._track), fs * 1.05),
            ("MAG", fs * 0.8)]
    widths = []
    for text, px in runs:
        p.setFont(_font(family, px, bold=True))
        widths.append(p.fontMetrics().horizontalAdvance(text))
    bw = sum(widths) + sp * 4
    apex_y = osp.y() - r
    box = QRectF(osp.x() - bw / 2.0, apex_y - fs * 0.5 - g["box_h"], bw,
                 g["box_h"])
    p.setPen(QPen(col, lw))
    p.drawRect(box)
    tx = box.left() + sp
    for (text, px), tw in zip(runs, widths):
        p.setFont(_font(family, px, bold=True))
        p.drawText(QRectF(tx, box.top(), tw, box.height()),
                   Qt.AlignmentFlag.AlignCenter, text)
        tx += tw + sp
    t = fs * 0.45
    p.setBrush(QBrush(col))
    p.drawPolygon(QPolygonF([QPointF(osp.x(), apex_y),
                             QPointF(osp.x() - t, apex_y - t),
                             QPointF(osp.x() + t, apex_y - t)]))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Corner blocks.
    p.setFont(_font(family, fs))
    lh = fs * 1.3
    top = 4.0 + status_chip_height(w) + 2.0
    tl_lines, arrow = top_left(read)
    y = _draw_lines(p, tl_lines, 6.0, top, lh)
    if arrow is not None:
        _wind_arrow(p, QPointF(6.0 + fs, y + fs), fs * 0.9,
                    arrow + 180.0 - up, lw)
    _draw_lines(p, top_right(read, now), 0.0, top, lh,
                align_right=True, right=w - 6.0)
    bl = bottom_left(enabled_layers(widget))
    _draw_lines(p, bl, 6.0, h - 6.0 - lh * len(bl), lh)

    _paint_vdev(p, vdev_geometry(w, h), vdev(read), family, lw)
    p.restore()


def _wind_arrow(p, c, length, screen_deg, lw):
    """The wind arrow: points the way the wind blows, rotated into the
    track-up screen (``WINDDIR`` is where it blows FROM)."""
    p.save()
    p.translate(c)
    p.rotate(screen_deg)
    p.setPen(QPen(WHITE, lw))
    p.drawLine(QPointF(0, length), QPointF(0, -length))
    head = length * 0.4
    p.drawLine(QPointF(0, -length), QPointF(-head * 0.6, -length + head))
    p.drawLine(QPointF(0, -length), QPointF(head * 0.6, -length + head))
    p.restore()


def _paint_vdev(p, g, state, family, lw):
    if state is None:
        return
    x0, y0, half, fs = g["x"], g["y0"], g["half"], g["fs"]
    p.setPen(QPen(WHITE, lw))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Fixed scale: a long centre reference, short ticks at +/-0.5 and +/-1.
    p.drawLine(QPointF(x0 - fs * 0.6, y0), QPointF(x0 + fs * 0.6, y0))
    for d in (-1.0, -0.5, 0.5, 1.0):
        y = y0 - d * half
        p.drawLine(QPointF(x0 - fs * 0.3, y), QPointF(x0 + fs * 0.3, y))
    if state["pointer"] is not None:
        y = vdev_pointer_y(g, state["pointer"])
        ds = fs * 0.45
        p.setPen(QPen(MAGENTA, lw))
        p.drawPolygon(QPolygonF([QPointF(x0, y - ds), QPointF(x0 + ds, y),
                                 QPointF(x0, y + ds), QPointF(x0 - ds, y)]))
    if state["flag"]:
        f = _font(family, fs, bold=True)
        p.setFont(f)
        fm = p.fontMetrics()
        pad = fs * 0.3
        tw = fm.horizontalAdvance("GS")
        box = QRectF(x0 - tw / 2.0 - pad, y0 - fm.height() / 2.0 - pad,
                     tw + 2 * pad, fm.height() + 2 * pad)
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.setPen(QPen(RED, max(2.0, fs * 0.12)))
        p.drawRect(box)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, "GS")
