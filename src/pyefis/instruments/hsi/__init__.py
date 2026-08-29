#  Copyright (c) 2013 Neil Domalik; 2018-2019 Garrett Herschleb
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import math
import time

from PyQt6.QtGui import *
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *


from pyefis import common
import pyavtools.fix as fix
from pyefis import common
from pyefis.instruments import helpers

# TODO: Add CDI and Glide Slope indicators and tick marks but make them
#       configurable.


class HSI(QGraphicsView):
    def __init__(self, parent=None, font_size=15, font_percent=None, fg_color=Qt.GlobalColor.white, bg_color=Qt.GlobalColor.black, gsi_enabled=False, cdi_enabled=False, font_family="DejaVu Sans Condensed"):
        super(HSI, self).__init__(parent)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0%); border: 0px")
        self.font_family = font_family
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.font_percent = None
        if font_percent:
            self.font_percent = font_percent
            font_size = qRound(self.font_percent * self.width())
        self.fontSize = font_size
        self.tickSize = self.fontSize * 0.7
        self.fg_color = fg_color
        self.bg_color = bg_color
        # Compass-disc fill opacity, percent: 100 = solid face (default), 0 =
        # transparent so the SVS/PFD behind shows through the circle. This fills
        # the round compass disc, not the rectangular widget box.
        self.bg_opacity = 100
        # Selected-course pointer colour (the triangle driven by COURSE). With
        # source_auto_color on (default), this magenta is used for a GPS source
        # and vloc_color (green) for a VOR/LOC source, selected by NAVSRC
        # (2=GPS, 0/1=NAV). Off -> the pointer is always course_color.
        self.course_color = "#ff00ff"
        self.source_auto_color = True
        self.vloc_color = "#00ff00"
        # Nav-source annunciation: a small "GPS" / "VLOC1" / "VLOC2" label on the
        # rose face, coloured to match the source. Refined to VOR/LOC when NAVTYPE
        # is published. On by default.
        self.source_label_enabled = True
        # CDI/GSI deviation-needle colour + width.
        self.needle_color = "#ffff00"
        self.needle_width = 3
        # Garmin-style heading bug (cyan): a marker that scrolls to the selected
        # heading from the HEADBUG FIX key. Off by default -- not every panel
        # publishes a selected heading (a MAVLink trim/cruise autopilot has
        # none), so enable it in the editor once a source exists.
        self.heading_bug_enabled = False
        self.heading_bug_color = "#00ffff"
        # GPS ground-track diamond (magenta): a marker on the rose at the current
        # magnetic GPS ground track (TRACKM). Garmin shows it whenever there is a
        # valid track. Gated on ground speed (GPS track is meaningless near zero
        # groundspeed) -- shown only at or above track_min_speed kt. On by
        # default; it self-hides when TRACKM/GS are absent, stale, or below the
        # speed gate, so it is safe on panels without a GPS track source.
        self.track_indicator_enabled = True
        self.track_color = "#ff00ff"
        self.track_min_speed = 5.0
        self.gsi_enabled = gsi_enabled
        self.cdi_enabled = cdi_enabled
        # P5a redesign option defaults (must match the InstrumentSpec Prop
        # defaults; the screenbuilder overrides these from the config).
        self.center_symbol = "aircraft"   # ownship glyph; 'none' hides
        self.readout_layout = "top_panel"  # top_panel | corners | split | none
        self.numeral_scale = 1.5           # rose numeral size multiplier
        self.depth_rings = False           # faint inner rings (off by default)
        # Soft drop shadow on the static elements -- rose disc, readout panel,
        # and (once #140 lands) the nav-source tab -- via the shared
        # helpers.SHADOW_* tokens (AER-392 / pyEfis#142). Off by default, same
        # as depth_rings above.
        self.shadow_enabled = False
        # Compass orientation (P5b.3). north_up/heading_up/track_up all render the
        # existing full-360 rotating rose UNCHANGED (their distinct behaviours are
        # a separate item; today the single rotating card serves all three). "arc"
        # selects a PARALLEL paint path (_paint_arc): the forward ~120 sector
        # spread across the width at an expanded angular scale, decluttered of the
        # rear rose. Default heading_up = today's behaviour.
        self.orientation = "heading_up"
        # HSI bearing pointers (P5b.2): two RMI-style needles (BRG1/BRG2), each
        # pointing to a station/waypoint, source-selected via BRG1SRC/BRG2SRC
        # (0=VOR1, 1=VOR2, 2=GPS). Off by default (not every panel has a bearing
        # source). bearing_color is the generic fallback; a needle is coloured by
        # its source (magenta GPS / green VOR, HSI-COLOR-001/-002) when the source
        # is known.
        self.bearing1_enabled = False
        self.bearing2_enabled = False
        self.bearing_color = "#00ffff"
        # List for tick mark visibility, Top, Bottom, Right, Left
        self.visiblePointers = [True, True, True, True]

        self._CdiOld = True
        self._CdiBad = True
        self._CdiFail = True

        self._GsiOld = True
        self._GsiBad = True
        self._GsiFail = True

        self._CourseOld = True
        self._CourseBad = True
        self._CourseFail = True

        self._HeadOld = True
        self._HeadBad = True
        self._HeadFail = True

        self._courseDeviation = 0
        self._glideSlopeIndicator = 0
        self.labels = list()

        self.item = fix.db.get_item("COURSE")
        self._courseSelect = self.item.value
        self.item.valueChanged[float].connect(self.setCoursePointer)
        self.item.oldChanged[bool].connect(self.setCourseOld)
        self.item.badChanged[bool].connect(self.setCourseBad)
        self.item.failChanged[bool].connect(self.setCourseFail)
        self.setCourseOld(self.item.old)
        self.setCourseBad(self.item.bad)
        self.setCourseFail(self.item.fail)

        if self.cdi_enabled:
            self.cdidb = fix.db.get_item("CDI")
            self._courseDeviation = self.cdidb.value
            self.cdidb.valueChanged[float].connect(self.setCdi)
            self.cdidb.oldChanged[bool].connect(self.setCdiOld)
            self.cdidb.badChanged[bool].connect(self.setCdiBad)
            self.cdidb.failChanged[bool].connect(self.setCdiFail)
            self.setCdiOld(self.cdidb.old)
            self.setCdiBad(self.cdidb.bad)
            self.setCdiFail(self.cdidb.fail)
        else:
            self._CdiOld = False
            self._CdiBad = False
            self._CdiFail = False
        if self.gsi_enabled:
            self.gsidb = fix.db.get_item("GSI")
            self._glideSlopeIndicator = self.gsidb.value
            self.gsidb.valueChanged[float].connect(self.setGsi)
            self.gsidb.oldChanged[bool].connect(self.setGsiOld)
            self.gsidb.badChanged[bool].connect(self.setGsiBad)
            self.gsidb.failChanged[bool].connect(self.setGsiFail)
            self.setGsiOld(self.gsidb.old)
            self.setGsiBad(self.gsidb.bad)
            self.setGsiFail(self.gsidb.fail)
        else:
            self._GsiOld = False
            self._GsiBad = False
            self._GsiFail = False

        self.head = fix.db.get_item("HEAD")
        self._heading = self.head.value
        self.head.valueChanged[float].connect(self.setHeading)
        self.head.oldChanged[bool].connect(self.setHeadOld)
        self.head.badChanged[bool].connect(self.setHeadBad)
        self.head.failChanged[bool].connect(self.setHeadFail)
        self.setHeadFail(self.head.fail)
        self.setHeadOld(self.head.old)
        self.setHeadBad(self.head.bad)
        self.setHeadFail(self.head.fail)

        # Heading-bug source (HEADBUG). Subscribe always (like CDI/GSI); the
        # marker is only drawn when heading_bug_enabled. Guarded so a database
        # without the key can't break construction.
        self._hdgBug = 0.0
        self.hdg_bug_item = None
        try:
            self.hdgbugdb = fix.db.get_item("HEADBUG")
            self._hdgBug = self.hdgbugdb.value or 0.0
            self.hdgbugdb.valueChanged[float].connect(self.setHdgBug)
        except Exception:
            self.hdgbugdb = None

        # GPS ground track (TRACK) + ground speed (GS) for the track diamond.
        # Subscribe always (the marker is drawn only when enabled); guarded so a
        # database without these keys can't break construction -- the diamond
        # then simply never shows. GS gates the marker by speed; if there is no
        # GS source the gate is skipped (track shown whenever valid).
        self._track = 0.0
        self._gs = 0.0
        self._TrackOld = True
        self._TrackBad = True
        self._TrackFail = True
        self.track_item = None
        try:
            self.trackdb = fix.db.get_item("TRACKM")
            self._track = self.trackdb.value or 0.0
            self.trackdb.valueChanged[float].connect(self.setTrack)
            self.trackdb.oldChanged[bool].connect(self.setTrackOld)
            self.trackdb.badChanged[bool].connect(self.setTrackBad)
            self.trackdb.failChanged[bool].connect(self.setTrackFail)
            self._TrackOld = self.trackdb.old
            self._TrackBad = self.trackdb.bad
            self._TrackFail = self.trackdb.fail
        except Exception:
            self.trackdb = None
        try:
            self.gsdb = fix.db.get_item("GS")
            self._gs = self.gsdb.value or 0.0
            self.gsdb.valueChanged[float].connect(self.setGs)
        except Exception:
            self.gsdb = None

        # Selected nav source (NAVSRC: 0=NAV1, 1=NAV2, 2=GPS) for source-based
        # colouring of the course pointer + CDI (magenta GPS / green VLOC).
        # Subscribed defensively; absent source -> _navsrc stays None and the
        # static colours are used.
        self._navsrc = None
        try:
            self.navsrcdb = fix.db.get_item("NAVSRC")
            self._navsrc = self.navsrcdb.value
            self.navsrcdb.valueChanged[float].connect(self.setNavsrc)
        except Exception:
            self.navsrcdb = None
        # Active source kind (NAVTYPE: 0=GPS, 1=VOR, 2=LOC, 3=LOC-BC) refines the
        # source label (VOR1/LOC1 vs the NAVSRC-only VLOC1). Defensive; absent ->
        # the label falls back to GPS/VLOCn from NAVSRC alone.
        self._navtype = None
        try:
            self.navtypedb = fix.db.get_item("NAVTYPE")
            self._navtype = self.navtypedb.value
            self.navtypedb.valueChanged[float].connect(self.setNavtype)
        except Exception:
            self.navtypedb = None
        # Glideslope/glidepath validity for the selected source (GSV: 1 = GS
        # present, 0 = none). A VOR has no glideslope, so GSV=0 hides the GS
        # needle while the lateral CDI stays. Defensive; absent -> the GS shows
        # on its own quality, preserving behaviour where GSV is not published.
        self._gsv = None
        try:
            self.gsvdb = fix.db.get_item("GSV")
            self._gsv = self.gsvdb.value
            self.gsvdb.valueChanged[float].connect(self.setGsv)
        except Exception:
            self.gsvdb = None
        # VOR TO/FROM for the selected source (TOFROM: 0=off/flag, 1=TO, 2=FROM).
        # Drawn as a triangle on the course line; hidden when 0 (LOC/GPS or no
        # signal). Defensive; absent -> not shown.
        self._tofrom = 0
        try:
            self.tofromdb = fix.db.get_item("TOFROM")
            self._tofrom = self.tofromdb.value or 0
            self.tofromdb.valueChanged[float].connect(self.setTofrom)
        except Exception:
            self.tofromdb = None

        # Bearing pointers (P5b.2): BRG1/BRG2 needle bearings + BRG1SRC/BRG2SRC
        # source selectors. Subscribed defensively (like TRACKM/NAVSRC) so a
        # database without the keys can't break construction -- the needle then
        # simply never shows. Per-pointer quality flags gate visibility
        # (HSI-FAIL-001) alongside the heading flag (HSI-ANN-001).
        self._brg = {1: 0.0, 2: 0.0}
        self._brgOld = {1: True, 2: True}
        self._brgBad = {1: True, 2: True}
        self._brgFail = {1: True, 2: True}
        self._brgSrc = {1: None, 2: None}
        self.brgdb = {1: None, 2: None}
        self.brgsrcdb = {1: None, 2: None}
        for _n in (1, 2):
            try:
                _it = fix.db.get_item("BRG%d" % _n)
                self.brgdb[_n] = _it
                self._brg[_n] = _it.value or 0.0
                self._brgOld[_n] = _it.old
                self._brgBad[_n] = _it.bad
                self._brgFail[_n] = _it.fail
                _it.valueChanged[float].connect(
                    lambda v, n=_n: self._setBrg(n, v))
                _it.oldChanged[bool].connect(
                    lambda b, n=_n: self._setBrgOld(n, b))
                _it.badChanged[bool].connect(
                    lambda b, n=_n: self._setBrgBad(n, b))
                _it.failChanged[bool].connect(
                    lambda b, n=_n: self._setBrgFail(n, b))
            except Exception:
                self.brgdb[_n] = None
            try:
                _si = fix.db.get_item("BRG%dSRC" % _n)
                self.brgsrcdb[_n] = _si
                self._brgSrc[_n] = _si.value
                _si.valueChanged[float].connect(
                    lambda v, n=_n: self._setBrgSrc(n, v))
            except Exception:
                self.brgsrcdb[_n] = None

        self._showCDI = not self.isOld()
        self._showGSI = not self.isOld()
        self._showHdgFlag = False
        self._showNavFlag = False
        self._showGsFlag = False
        self.cardinal = ["N", "E", "S", "W"]
        self.course_pointer = None
        self.myparent = parent
        self.update_period = None

    def getRatio(self):
        # Return X for 1:x specifying the ratio for this instrument
        return 1

    def resizeEvent(self, event):
        if self.font_percent:
            self.fontSize = qRound(self.font_percent * self.width())
        self.tickSize = self.fontSize * 0.7
        self.scene = QGraphicsScene(0, 0, self.width(), self.height())
        self.cx = self.width() / 2.0
        self.cy = self.height() / 2.0
        self.r = self.height() / 2.0 - 5.0
        # Readout gutter (P5a iter4b): layouts that place a single sectioned
        # readout panel OUTSIDE the rose shrink + shift the rose to open room.
        # Everything downstream derives from cx/cy/r, so the whole instrument
        # follows (Bill 2026-08-02).
        self._gutter = 0.0
        _rl = getattr(self, "readout_layout", "top_panel")
        if _rl in ("top_panel", "split"):
            self._gutter = self.height() * 0.16
            self.r = min(self.width(), self.height() - self._gutter) / 2.0 - 5.0
            self.cy = self._gutter + (self.height() - self._gutter) / 2.0
        # Reserve clearance for the rose drop shadow (AER-392): the disc sat
        # only 5px from the widget edge, nowhere near enough room for a
        # blurred halo to resolve without hard-clipping against the widget
        # bounds (gotcha #2). Shrinking the rose itself when the shadow is on
        # -- instead of clamping the blur radius after the fact -- guarantees
        # the halo always has the room bake_blurred_silhouette/the drop-shadow
        # effect actually needs (SHADOW_CANVAS_PAD_RATIO), at the cost of a
        # slightly smaller rose. No-op (0px) when shadows are off.
        self._rose_shadow_blur = 0.0
        if getattr(self, "shadow_enabled", False):
            self._rose_shadow_blur = self.fontSize * helpers.SHADOW_BLUR_RATIO
            self.r -= self._rose_shadow_blur * helpers.SHADOW_CANVAS_PAD_RATIO
        self.cdippw = self.r * 0.5
        self.gsipph = self.r * 0.5

        # Compass-disc background fill, behind the rose (z=-1), honouring
        # bg_opacity: a solid face by default (1.0), or transparent (0.0) so the
        # SVS/PFD behind the round instrument shows through. Drawn as a scene
        # item (not drawBackground) so it is rendered fresh and isn't subject to
        # the view's background caching.
        _op = max(0.0, min(1.0, float(getattr(self, "bg_opacity", 100)) / 100.0))
        if _op > 0.0:
            _disc = QColor(self.bg_color)
            _disc.setAlphaF(_op)
            _bgitem = self.scene.addEllipse(
                self.cx - self.r, self.cy - self.r, self.r * 2.0, self.r * 2.0,
                QPen(Qt.PenStyle.NoPen), QBrush(_disc))
            _bgitem.setZValue(-1)
            # Rose drop shadow (Option 2, AER-392): a QGraphicsDropShadowEffect
            # on this scene item, captured for free by the existing rose bake
            # (_rose_image -- rendered once per resize, then pre-rotated and
            # cached by _rotated_rose_image). Zero offset matters here
            # specifically: the disc is circular and the bake gets ROTATED per
            # heading, so a symmetric halo is the only shadow that looks
            # identical at every heading (gotcha #1) -- an offset one would
            # make the implied light source appear to orbit as the card turns.
            if getattr(self, "shadow_enabled", False):
                _bgitem.setGraphicsEffect(
                    helpers.drop_shadow_effect(self._rose_shadow_blur))

        # Setup Pens
        compassPen = QPen(QColor(self.fg_color), self.fontSize * 0.02)
        textBrush = QBrush(QColor(self.fg_color))
        nobrush = QBrush()

        _cp = self._course_pointer_color()
        headingPen = QPen(_cp)
        headingBrush = QBrush(_cp)
        headingPen.setWidth(1)


        f = QFont(self.font_family)
        f.setPixelSize(self.fontSize)

        # (count, text) for numerals drawn screen-upright in paintEvent. The
        # scene label items (self.labels) are still built below -- kept for the
        # fail/opacity contract the tests assert -- but hidden during the rose
        # bake so only the upright paintEvent numerals show (Bill 2026-08-02).
        self._rose_labels = []

        for count in range(0, 360, 5):
            angle = (count) * math.pi / 180.0
            cosa = math.cos(angle)
            sina = math.sin(angle)
            iy1 = -self.r
            # Tick weight + length hierarchy (P5a iter2): 30deg heaviest/longest,
            # 10deg medium, 5deg fine. Gives the rose structure vs one hairline.
            if count % 90 == 0:
                iy2 = -self.r + self.tickSize * 1.25
                _tw = self.fontSize * 0.055
            elif count % 30 == 0:
                iy2 = -self.r + self.tickSize * 1.15
                _tw = self.fontSize * 0.045
            elif count % 10 == 0:
                iy2 = -self.r + self.tickSize
                _tw = self.fontSize * 0.03
            else:
                iy2 = -self.r + self.tickSize * 0.5
                _tw = self.fontSize * 0.018
            tickPen = QPen(QColor(self.fg_color), max(1.0, _tw))
            x1 = (-iy1*sina) + self.cx # (ix*cosa - iy*sina) ix factor removed Since x is 0
            y1 = iy1*cosa + self.cy # (iy*cosa + ix*sina)
            x2 = (-iy2*sina) + self.cx
            y2 = iy2*cosa + self.cy
            self.scene.addLine(x1, y1, x2, y2, tickPen)
            if count % 90 == 0:
                t = self.scene.addSimpleText(self.cardinal[int(count / 90)], f)
                br = t.sceneBoundingRect()
                # Upright numerals (Bill 2026-08-02, Airhart): stay screen-level as
                # the card rotates; position still rotates. Was t.setRotation(count).
                t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                t.setPen(compassPen)
                t.setBrush(textBrush)
                iy3 = -self.r + self.tickSize*1.1
                ix3 = -br.width()/2
                x3 = (ix3*cosa - iy3*sina) + self.cx
                y3 = (iy3*cosa + ix3*sina) + self.cy
                t.setPos(x3, y3)
                self.labels.append(t)
                self._rose_labels.append((count, self.cardinal[int(count / 90)]))
            elif count % 30 == 0:
                text = str(int(count / 10))
                t = self.scene.addSimpleText(text, f)
                br = t.sceneBoundingRect()
                # Upright numerals (Bill 2026-08-02, Airhart): stay screen-level as
                # the card rotates; position still rotates. Was t.setRotation(count).
                t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                t.setPen(compassPen)
                t.setBrush(textBrush)
                iy3 = -self.r + self.tickSize*1.1
                ix3 = -br.width()/2
                x3 = (ix3*cosa - iy3*sina) + self.cx
                y3 = (iy3*cosa + ix3*sina) + self.cy
                t.setPos(x3, y3)
                self.labels.append(t)
                self._rose_labels.append((count, text))

        # Course pointer (driven by COURSE): the selected-course triangle,
        # coloured by source (magenta GPS / green VLOC) when source_auto_color is
        # on, else course_color.
        triangle = self.course_pointer_polygon()
        self.course_pointer = self.scene.addPolygon(triangle, headingPen, headingBrush)
        # The visible course pointer + CDI are drawn in paintEvent, rotated to the
        # course on the heading-up card (HSI style); hide the scene triangle so the
        # head is not doubled. The item is kept for course/state bookkeeping.
        self.course_pointer.setVisible(False)

        # Garmin-style heading bug (cyan): scrolls to the HEADBUG selected
        # heading on the inside of the ring. Drawn only when enabled.
        self.hdg_bug_item = None
        if getattr(self, "heading_bug_enabled", False):
            _hbc = QColor(self.heading_bug_color)
            self.hdg_bug_item = self.scene.addPolygon(
                self._hdg_bug_polygon(), QPen(_hbc), QBrush(_hbc))

        # GPS ground-track diamond (magenta). Created when enabled; its
        # visibility is gated on speed/quality by _update_track().
        self.track_item = None
        if getattr(self, "track_indicator_enabled", False):
            _tc = QColor(self.track_color)
            self.track_item = self.scene.addPolygon(
                self._track_diamond_polygon(), QPen(_tc), QBrush(_tc))
            self._update_track()

        self.setScene(self.scene)
        # Clear any prior view rotation before re-applying. resizeEvent can fire
        # repeatedly (initial layout settling, any geometry change), and the
        # rotation is a view transform that persists across the scene rebuild --
        # without this reset each call stacked another -heading rotation, baking
        # in a permanent offset (the card showed heading+offset, e.g. 290 when
        # actually 052). setHeading then tracks incrementally from this baseline.
        self.resetTransform()
        self.rotate(-self._heading)

        # Draws the static overlay stuff to a pixmap
        self.map = QPixmap(self.width(), self.height())
        self.map.fill(Qt.GlobalColor.transparent)
        p = QPainter(self.map)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # set the width and height for conveinience
        # w = self.width()
        # h = self.height()

        p.setPen(QPen(QColor(self.fg_color),self.fontSize * 0.07))
        p.setBrush(QColor(Qt.GlobalColor.transparent))
        # Outer ring
        p.drawEllipse(QRectF(self.cx-self.r, self.cy-self.r, self.r*2.0, self.r*2.0))
        # Depth rings (P5a iter2): faint concentric rings inside the outer ring.
        # A light STRUCTURAL cue only -- NOT true depth (real depth comes from the
        # translucent disc over the live map + rim treatment). Config-gated so the
        # look can be compared with/without them (Bill 2026-08-02).
        if getattr(self, "depth_rings", True):
            for _rad, _af in ((self.r * 0.78, 0.35), (self.r * 0.52, 0.22)):
                _rc = QColor(self.fg_color); _rc.setAlphaF(_af)
                p.setPen(QPen(_rc, max(1.0, self.fontSize * 0.02)))
                p.setBrush(QColor(Qt.GlobalColor.transparent))
                p.drawEllipse(QRectF(self.cx - _rad, self.cy - _rad, _rad * 2.0, _rad * 2.0))
        # Draw the pointer marks
        # Fixed top lubber-line triangle, points down at the rose. Replaces the
        # four yellow cardinal pointer marks (Bill 2026-08-02: remove the yellow
        # cardinal lozenges; a single neutral top lubber reads cleaner/modern).
        _lub = self.fontSize * 0.7
        _lubber = QPolygonF([
            QPointF(self.cx - _lub * 0.55, self.cy - self.r - _lub),
            QPointF(self.cx + _lub * 0.55, self.cy - self.r - _lub),
            QPointF(self.cx, self.cy - self.r + _lub * 0.35),
        ])
        p.setPen(QPen(QColor(self.fg_color), max(1, int(self.fontSize * 0.05))))
        p.setBrush(QBrush(QColor(self.fg_color)))
        p.drawPolygon(_lubber)

        # Center ownship symbol (P5a iter2). Fixed, points up (drawn in the
        # un-rotated overlay). An AIRCRAFT silhouette, deliberately NOT a triangle:
        # a triangle reads as the TO/FROM / course indicator on many HSIs
        # (Bill 2026-08-02). center_symbol is config-selectable (default 'aircraft',
        # 'none' to hide); more styles can be offered in the configurator later.
        _sym = getattr(self, "center_symbol", "aircraft")
        if _sym != "none":
            s = self.r * 0.16
            ac_pen = QPen(QColor(self.fg_color), max(1.5, self.fontSize * 0.05))
            ac_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            ac_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(ac_pen)
            p.setBrush(QColor(Qt.GlobalColor.transparent))
            p.drawLine(QLineF(self.cx, self.cy - s, self.cx, self.cy + s))          # fuselage
            p.drawLine(QLineF(self.cx - s, self.cy, self.cx + s, self.cy))          # wings
            p.drawLine(QLineF(self.cx - s * 0.4, self.cy + s * 0.7,
                              self.cx + s * 0.4, self.cy + s * 0.7))                 # tailplane

        self.overlay = self.map.toImage()



    def course_pointer_polygon(self):
        inc = int(self.tickSize)
        iyb = -self.r
        points = [ (inc, -self.r),
                  (-inc, -self.r),
                  (0, -self.r + inc)]
        angle = (self._courseSelect) * math.pi / 180
        cosa = math.cos(angle)
        sina = math.sin(angle)

        points = [((ix*cosa - iy*sina), (iy*cosa + ix*sina)) for ix,iy in points]
        points = [QPointF((ix + self.cx), (iy + self.cy)) for ix,iy in points]
        triangle = QPolygonF(points)
        return triangle

    def _hdg_bug_polygon(self):
        # Classic notched heading-bug shape on the inside of the ring, rotated
        # to the selected heading (_hdgBug).
        inc = int(self.tickSize)
        w = inc
        h = inc * 1.3
        yo = -self.r            # outer edge (at the ring)
        yi = -self.r + h        # inner base
        yn = -self.r + h * 0.5  # notch depth
        points = [(-w, yi), (-w, yo), (-w * 0.35, yo), (-w * 0.35, yn),
                  (w * 0.35, yn), (w * 0.35, yo), (w, yo), (w, yi)]
        angle = (self._hdgBug) * math.pi / 180.0
        cosa = math.cos(angle)
        sina = math.sin(angle)
        points = [((ix * cosa - iy * sina), (iy * cosa + ix * sina))
                  for ix, iy in points]
        points = [QPointF((ix + self.cx), (iy + self.cy)) for ix, iy in points]
        return QPolygonF(points)

    def setHdgBug(self, value):
        if value != self._hdgBug:
            self._hdgBug = common.bounds(0, 360, value)
            if self.hdg_bug_item is not None:
                self.hdg_bug_item.setPolygon(self._hdg_bug_polygon())

    def _track_diamond_polygon(self):
        # Small diamond on the rose face near the outer edge, rotated to the GPS
        # ground track (_track). Scene-space like the other markers, so the view
        # rotation places it at (track - heading) from the lubber line.
        s = self.tickSize * 0.55
        yc = -self.r + self.tickSize * 1.3
        points = [(0, yc - s), (s, yc), (0, yc + s), (-s, yc)]
        angle = self._track * math.pi / 180.0
        cosa = math.cos(angle)
        sina = math.sin(angle)
        points = [((ix * cosa - iy * sina), (iy * cosa + ix * sina))
                  for ix, iy in points]
        points = [QPointF((ix + self.cx), (iy + self.cy)) for ix, iy in points]
        return QPolygonF(points)

    def _track_visible(self):
        # Only with a valid track and, when a GS source exists, at or above the
        # speed gate (GPS track is noise near zero groundspeed).
        if not getattr(self, "track_indicator_enabled", False):
            return False
        if self._TrackOld or self._TrackBad or self._TrackFail:
            return False
        if self.gsdb is not None and self._gs < self.track_min_speed:
            return False
        return True

    def _update_track(self):
        if self.track_item is None:
            return
        vis = self._track_visible()
        self.track_item.setVisible(vis)
        if vis:
            self.track_item.setPolygon(self._track_diamond_polygon())

    def setTrack(self, value):
        v = common.bounds(0, 360, value)
        if v != self._track:
            self._track = v
            self._update_track()

    def setGs(self, value):
        if value != self._gs:
            self._gs = value
            self._update_track()

    def setTrackOld(self, old):
        self._TrackOld = old
        self._update_track()

    def setTrackBad(self, bad):
        self._TrackBad = bad
        self._update_track()

    def setTrackFail(self, fail):
        self._TrackFail = fail
        self._update_track()

    def _rose_image(self):
        """The static rose (disc, ticks, cardinal/numeral labels) baked
        UNROTATED at 2x supersample -- once per scene build (#94). The
        heading rotation is applied at blit time in paintEvent; the
        dynamic card items (heading bug, track diamond) are hidden
        during the bake and drawn directly under the same rotation.
        The cache holds the scene OBJECT (resizeEvent replaces the
        scene wholesale; id() could be recycled -- same hazard as the
        tape strip cache, #93)."""
        scene = self.scene
        w, hgt = self.width(), self.height()
        key = (w, hgt, float(self.fontSize))
        cached = getattr(self, "_rose_cache", None)
        if (cached is not None and cached[0] is scene
                and cached[1] == key):
            return cached[2]
        ss = 2
        img = QImage(w * ss, hgt * ss,
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        # Hide the dynamic card items AND the scene numeral labels during the
        # bake: numerals are drawn screen-upright in paintEvent, not baked into
        # the rotating rose (they must stay horizontal as the card turns).
        dyn = [i for i in (self.hdg_bug_item, self.track_item)
               if i is not None] + list(self.labels)
        vis = [i.isVisible() for i in dyn]
        for i in dyn:
            i.setVisible(False)
        try:
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.scene.render(p, QRectF(0, 0, w * ss, hgt * ss),
                              QRectF(0, 0, w, hgt))
            p.end()
        finally:
            for i, v in zip(dyn, vis):
                i.setVisible(v)
        self._rose_cache = (scene, key, img)
        return img

    # Pre-rotated rose blit cache (#126) tuning: heading quantization step
    # and how many rotated frames to retain (a few entries absorb heading
    # jitter dithering across a step boundary).
    _ROSE_ROT_STEP_DEG = 0.5
    _ROSE_ROT_CACHE_MAX = 4

    def _rotated_rose_image(self):
        """The rose pre-rotated to the current heading, widget-sized, cached
        by heading quantized to _ROSE_ROT_STEP_DEG (#126). The per-frame
        smooth-filtered rotate+downscale of the 2x bake was the hottest
        paint leaf in flight profiling (8.2% of GIL-held samples on the
        N150); caching the rotated result makes the frame cost an unscaled
        drawImage, and the filter runs only when the heading crosses a step
        (~6/s in a standard-rate turn, ~never in cruise). Max card error is
        a quarter degree -- about one pixel at the rose rim at typical
        sizes; the heading bug, track diamond, needles and numerals still
        use the exact heading. Keyed on the bake's cacheKey() so scene
        rebuilds (resize) invalidate this cache exactly when they
        invalidate the bake."""
        base = self._rose_image()
        step = self._ROSE_ROT_STEP_DEG
        q = (round(self._heading / step) * step) % 360.0
        dpr = float(self.devicePixelRatioF())
        key = (q, base.cacheKey(), dpr)
        cache = getattr(self, "_rot_rose_cache", None)
        if cache is None:
            cache = self._rot_rose_cache = {}
        img = cache.get(key)
        if img is not None:
            return img
        w, hgt = self.width(), self.height()
        img = QImage(max(1, int(round(w * dpr))),
                     max(1, int(round(hgt * dpr))),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(self.cx, self.cy)
        p.rotate(-q)
        p.drawImage(QRectF(-self.cx, -self.cy, w, hgt), base)
        p.end()
        cache[key] = img
        while len(cache) > self._ROSE_ROT_CACHE_MAX:
            del cache[next(iter(cache))]
        return img

    def paintEvent(self, event):
        # Arc orientation (P5b.3) is a parallel paint path; every other
        # orientation renders the full 360 rose below, byte-for-byte unchanged.
        if getattr(self, "orientation", "heading_up") == "arc":
            self._paint_arc(event)
            return
        # The rose is static art on a rotating card: blit a cached
        # pre-rotated bake instead of having QGraphicsView re-render
        # ~84 items per frame (#94 -- the HSI was ~24% of all GIL time
        # in flight) or smooth-filtering the rotation every frame
        # (#126 -- see _rotated_rose_image). The heading bug and
        # track diamond are the only dynamic card items; they are drawn
        # here under the exact-heading rotation, in scene coordinates,
        # exactly as their scene polygons are computed. setHeading still
        # rotates the (now unpainted) view so scene-item updates keep
        # scheduling repaints.
        c = QPainter(self.viewport())
        c.setRenderHint(QPainter.RenderHint.Antialiasing)
        c.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # 1:1 blit of the pre-rotated rose (#126); the rotation filter cost
        # lives in _rotated_rose_image and is paid only on step crossings.
        c.drawImage(self.rect(), self._rotated_rose_image())
        c.save()
        c.translate(self.cx, self.cy)
        c.rotate(-self._heading)
        c.translate(-self.cx, -self.cy)
        if self.hdg_bug_item is not None:
            _hbc = QColor(self.heading_bug_color)
            c.setPen(QPen(_hbc))
            c.setBrush(QBrush(_hbc))
            c.drawPolygon(self._hdg_bug_polygon())
        if self.track_item is not None and self.track_item.isVisible():
            _tc = QColor(self.track_color)
            c.setPen(QPen(_tc))
            c.setBrush(QBrush(_tc))
            c.drawPolygon(self._track_diamond_polygon())
        c.restore()

        # Put the static overlay image on the view
        c.drawImage(self.rect(), self.overlay)

        # Compass numerals/letters drawn screen-upright at their (count - heading)
        # positions so they stay HORIZONTAL as the card rotates (Bill 2026-08-02),
        # instead of being baked into the rotating rose. Size is configurable via
        # numeral_scale. Hidden on fail, matching changeFail's label opacity.
        if not self.isFail():
            nsize = max(10, int(self.fontSize * getattr(self, "numeral_scale", 1.5)))
            nf = QFont(self.font_family)
            nf.setPixelSize(nsize)
            c.setFont(nf)
            c.setPen(QPen(QColor(self.fg_color)))
            _Rlbl = self.r - self.tickSize * 1.5 - nsize * 0.55
            _bw = nsize * 3.0; _bh = nsize * 1.6
            for _cnt, _txt in getattr(self, "_rose_labels", ()):
                _th = (_cnt - self._heading) * math.pi / 180.0
                _lx = self.cx + _Rlbl * math.sin(_th)
                _ly = self.cy - _Rlbl * math.cos(_th)
                c.drawText(QRectF(_lx - _bw / 2, _ly - _bh / 2, _bw, _bh),
                           int(Qt.AlignmentFlag.AlignCenter), _txt)


        # Bearing pointers (P5b.2): RMI needles to the selected stations, drawn
        # BEFORE the course/CDI assembly so the deviation bar is never overridden
        # (visually separated by draw order, hsi_widget_spec sec 6.8). Each shows
        # only when valid (heading + its own BRGn); source-coloured.
        for _n in (1, 2):
            if self._bearing_visible(_n):
                self._draw_bearing_needle(c, _n)

        compassPen = QPen(QColor(self.fg_color))
        cdiPen = QPen(self._source_color() or QColor(self.needle_color))
        cdiPen.setWidth(int(getattr(self, "needle_width", 3)))
        c.setRenderHint(QPainter.RenderHint.Antialiasing)


        # Course pointer + lateral deviation (CDI) + TO/FROM as one assembly,
        # rotated to the selected course on the heading-up card (on-screen course
        # angle = COURSE - HEADING) so it turns with the rose like a real HSI.
        if self.cdi_enabled or self.gsi_enabled:
            ang = (self._courseSelect - self._heading) * math.pi / 180.0
            ca = math.cos(ang); sa = math.sin(ang)

            def _p(lx, ly):   # local (lateral, along; -along = toward course head)
                return QPointF(self.cx + lx*ca - ly*sa, self.cy + ly*ca + lx*sa)

            ext = self.r - self.fontSize * 2.0
            bar = self.cdippw
            self._showCDI = self.cdi_enabled and not (self._CdiOld or self._CdiBad)
            self._showGSI = self.gsi_enabled and (self._gsv is None or self._gsv >= 0.5) \
                and not (self._GsiOld or self._GsiBad or self._GsiFail)

            if self.cdi_enabled:
                # Lateral deviation scale dots (white) along the lateral axis.
                c.setPen(QPen(QColor(self.fg_color)))
                c.setBrush(QBrush(QColor(self.fg_color)))
                dotr = max(1.5, self.tickSize * 0.16)
                for dev in (-1.0, -2.0/3.0, -1.0/3.0, 1.0/3.0, 2.0/3.0, 1.0):
                    c.drawEllipse(_p(dev * bar, 0.0), dotr, dotr)
                # Course pointer (source colour): head + tail through centre with
                # an arrowhead; the CDI bar (middle) carries the lateral deviation.
                cpc = self._course_pointer_color()
                cw = max(2, int(getattr(self, "needle_width", 3)))
                c.setPen(QPen(cpc, cw)); c.setBrush(QBrush(cpc))
                arr = self.tickSize
                c.drawLine(_p(0.0, bar), _p(0.0, ext))                     # tail
                c.drawLine(_p(0.0, -bar), _p(0.0, -ext + arr))             # head
                c.drawPolygon(QPolygonF([_p(0.0, -ext), _p(arr * 0.55, -ext + arr),
                                         _p(-arr * 0.55, -ext + arr)]))    # arrowhead
                if self._showCDI:
                    off = self._courseDeviation * bar
                    c.drawLine(_p(off, -bar), _p(off, bar))                # CDI bar
                # TO/FROM triangle: apex toward the head (TO) or tail (FROM).
                tf = int(round(self._tofrom)) if self._tofrom else 0
                if self._showCDI and tf in (1, 2):
                    rr = self.r * 0.42
                    s = self.tickSize * 0.6
                    length = self.tickSize * 1.1
                    if tf == 1:
                        pts = [(0.0, -(rr + length)), (s, -rr), (-s, -rr)]
                    else:
                        pts = [(0.0, -(rr - length)), (s, -rr), (-s, -rr)]
                    c.drawPolygon(QPolygonF([_p(lx, ly) for lx, ly in pts]))

            if self.gsi_enabled and (self._gsv is None or self._gsv >= 0.5):
                # Glideslope/glidepath: a vertical deviation scale on the RIGHT of
                # the rose (HSI convention) with a source-coloured diamond pointer.
                # Centre = on path; two dots each side. Hidden when there is no
                # glideslope (e.g. a VOR).
                gx = self.cx + self.r * 0.72
                grange = self.gsipph
                c.setPen(QPen(QColor(self.fg_color)))
                c.setBrush(QBrush(QColor(self.fg_color)))
                gdot = max(1.5, self.tickSize * 0.16)
                c.drawLine(qRound(gx - self.tickSize*0.55), qRound(self.cy),
                           qRound(gx + self.tickSize*0.55), qRound(self.cy))
                for dev in (-1.0, -0.5, 0.5, 1.0):
                    c.drawEllipse(QPointF(gx, self.cy - dev*grange), gdot, gdot)
                if self._showGSI:
                    gsc = self._source_color() or QColor(self.needle_color)
                    c.setPen(QPen(gsc)); c.setBrush(QBrush(gsc))
                    gy = self.cy - self._glideSlopeIndicator * grange
                    ds = self.tickSize * 0.6
                    c.drawPolygon(QPolygonF([QPointF(gx, gy - ds), QPointF(gx + ds, gy),
                                             QPointF(gx, gy + ds), QPointF(gx - ds, gy)]))

        # Nav-source annunciation, coloured to match the active source. In
        # `readout_layout: top_panel` this is drawn as a tab on the HDG | MAG |
        # CRS panel's left edge instead (_draw_source_tab, via _draw_readouts
        # below) -- pyEfis#140. Other layouts (corners/split/none) draw no such
        # panel, so they keep this plain top-left label. Its bounding box is
        # stored as a tap target -- tapping it cycles NAVSRC (mousePressEvent).
        self._source_label_rect = None
        if getattr(self, "readout_layout", "top_panel") != "top_panel" \
                and getattr(self, "source_label_enabled", True):
            label = self._source_label()
            if label:
                c.setPen(QPen(self._source_color() or QColor(self.course_color)))
                lf = QFont(self.font_family)
                lf.setPixelSize(int(self.fontSize))
                c.setFont(lf)
                lx = qRound(self.width() * 0.03)
                ly = qRound(self.fontSize * 1.2)
                c.drawText(lx, ly, label)
                fm = c.fontMetrics()
                pad = int(self.fontSize * 0.5)
                self._source_label_rect = (lx - pad, ly - fm.ascent() - pad,
                                           fm.horizontalAdvance(label) + 2*pad,
                                           fm.height() + 2*pad)

        # Per-pointer bearing-source labels (P5b.2), mirroring the tappable
        # nav-source annunciation: pointer 1 bottom-left, pointer 2 bottom-right,
        # source-coloured, tapping cycles BRGnSRC. A trailing "X" annunciates an
        # invalid selected source (the pointer's own BRGn old/bad/fail), the
        # §7 under-specified surface (source-selector requirement candidate --
        # routed through instrument_verification, not authored here).
        self._brg_label_rect = {1: None, 2: None}
        for _n in (1, 2):
            if not getattr(self, "bearing%d_enabled" % _n, False):
                continue
            if self.brgdb[_n] is None and self.brgsrcdb[_n] is None:
                continue
            txt = self._bearing_src_label(_n)
            if not txt:
                continue
            invalid = (self.brgdb[_n] is None or self._brgOld[_n]
                       or self._brgBad[_n] or self._brgFail[_n])
            if invalid:
                txt = txt + " X"
            lf = QFont(self.font_family)
            lf.setPixelSize(int(self.fontSize * 0.85))
            c.setFont(lf)
            fm = c.fontMetrics()
            tw = fm.horizontalAdvance(txt)
            th = fm.height()
            _bc = QColor(255, 150, 0) if invalid else self._bearing_color(_n)
            c.setPen(QPen(_bc))
            ly = qRound(self.height() - self.fontSize * 0.5)
            if _n == 1:
                lx = qRound(self.width() * 0.03)
            else:
                lx = qRound(self.width() * 0.97 - tw)
            c.drawText(lx, ly, txt)
            pad = int(self.fontSize * 0.5)
            self._brg_label_rect[_n] = (lx - pad, ly - fm.ascent() - pad,
                                        tw + 2 * pad, th + 2 * pad)

        # Warning flags (AC 25-11B: warnings red). A flag positively annunciates
        # an invalid signal, distinct from merely hiding an element -- see
        # hsi_widget_spec.md sec 7.1. Heading (compass) flag: HEAD invalid.
        self._showHdgFlag = self._HeadFail or self._HeadBad
        if self._showHdgFlag:
            self._draw_flag(c, "HDG", self.cx, self.fontSize * 1.1)
        # NAV (lateral) flag: selected lateral source invalid. The CDI bar is
        # already removed by _showCDI; the flag positively annunciates the loss.
        self._showNavFlag = self._CdiFail or self._CdiBad
        if self._showNavFlag:
            self._draw_flag(c, "NAV", self.cx - self.r * 0.4, self.cy)
        # GS flag: glideslope expected (present per GSV) but its signal is
        # unreliable (bad/failed). The diamond (_showGSI) already excludes bad/fail,
        # so the diamond and this flag are mutually exclusive. Distinct from 'no GS
        # present' (GSV<0.5), where the scale is simply absent -- no flag.
        self._showGsFlag = (self.gsi_enabled
                            and self._gsv is not None and self._gsv >= 0.5
                            and (self._GsiFail or self._GsiBad))
        if self._showGsFlag:
            self._draw_flag(c, "GS", self.cx + self.r * 0.72, self.cy)

        # Integral heading/selected-heading/course readout boxes (P5a iter3),
        # screen-fixed, placement selectable via readout_layout.
        self._draw_readouts(c)

    def _readout_shadow_image(self, rect, radius):
        """Cached blurred silhouette of one readout-panel/box shell (Option 4,
        AER-392): the shell is static geometry -- position/size change only on
        resize -- and a shadow silhouette is colour-independent, so ONE bake
        serves every NAVSRC state and every value the panel shows, at zero
        per-frame cost (gotcha #3). Keyed on the rect + widget size, so a
        resize (or a readout_layout change, which moves the rect) rebuilds it.

        The blur radius is capped to the actual on-screen clearance around
        `rect` -- gotcha #2's other case: this panel can sit close to the
        widget edge (the top_panel layout's gutter is thin), and baking a
        halo bigger than that clearance would clip it into a hard edge at the
        real widget boundary. Returns None when there isn't enough clearance
        to draw a shadow at all worth showing.
        """
        margin = min(rect.y(), self.height() - rect.bottom(),
                     rect.x(), self.width() - rect.right())
        blur = min(self.fontSize * helpers.SHADOW_BLUR_RATIO,
                   max(0.0, margin) / helpers.SHADOW_CANVAS_PAD_RATIO)
        if blur < 1.0:
            return None
        key = (round(rect.x(), 1), round(rect.y(), 1),
               round(rect.width(), 1), round(rect.height(), 1),
               round(radius, 1), round(blur, 1), self.width(), self.height())
        cache = getattr(self, "_readout_shadow_cache", None)
        if cache is not None and cache[0] == key:
            return cache[1]

        def _paint_shape(p):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(Qt.GlobalColor.black))
            p.drawRoundedRect(rect, radius, radius)

        result = helpers.bake_blurred_silhouette(
            self.width(), self.height(), _paint_shape, blur)
        self._readout_shadow_cache = (key, result)
        return result

    def _draw_readout_shadow(self, c, rect, radius):
        if not getattr(self, "shadow_enabled", False):
            return
        baked = self._readout_shadow_image(rect, radius)
        if baked is None:
            return
        img, pad = baked
        c.drawImage(QPointF(-pad, -pad), img)

    def _draw_readout_box(self, c, ax, ay, anchor, label, value, color):
        """One boxed readout (small label + degree value) anchored at (ax, ay).
        anchor = 2-char h/v code: h in l/c/r, v in t/m/b. Screen-fixed; a
        translucent black fill keeps it legible over the map/terrain."""
        bw = self.fontSize * 3.6
        bh = self.fontSize * 2.4
        x = ax if anchor[0] == 'l' else (ax - bw if anchor[0] == 'r' else ax - bw / 2.0)
        y = ay if anchor[1] == 't' else (ay - bh if anchor[1] == 'b' else ay - bh / 2.0)
        box = QRectF(x, y, bw, bh)
        col = QColor(color)
        self._draw_readout_shadow(c, box, self.fontSize * 0.3)
        # Shared house style (helpers.READOUT_*) -- the same primitive the tape
        # readout boxes draw through (P5c), so the two cannot drift. This
        # variant keeps its own fill/border alphas: the border is the value's
        # own colour at full strength, which is what distinguishes the cyan
        # selected-heading box from the source-coloured course box.
        helpers.draw_readout_panel(
            c, box, self.fontSize * 0.3, col,
            pen_width=self.fontSize * helpers.READOUT_PEN_RATIO,
            fill_alpha=0.55, border_alpha=1.0,
        )
        f = QFont(self.font_family)
        if label:
            f.setPixelSize(max(9, int(self.fontSize * 0.64)))
            f.setBold(True)
            c.setFont(f); c.setPen(QPen(col))
            c.drawText(QRectF(x, y + self.fontSize * 0.12, bw, self.fontSize * 0.8),
                       int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                       label)
            vy = y + self.fontSize * 0.85
            vh = bh - self.fontSize * 0.95
        else:
            vy = y; vh = bh
        f.setPixelSize(max(12, int(self.fontSize * 1.18)))
        c.setFont(f); c.setPen(QPen(QColor(self.fg_color)))
        c.drawText(QRectF(x, vy, bw, vh),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                   value)

    def _draw_readouts(self, c):
        """Integral readout boxes: actual heading (HEAD), selected heading
        (HEADBUG, cyan), selected course (COURSE, source-coloured). Placement is
        config-selectable via readout_layout so the configurator can offer
        vendor-style presets (Bill 2026-08-02)."""
        layout = getattr(self, "readout_layout", "garmin")
        if layout == "none":
            return

        def _deg(v):
            try:
                return "%03d°" % (int(round(float(v))) % 360)
            except Exception:
                return "---°"

        hdg = _deg(self._heading)                                  # actual
        crs = _deg(self._courseSelect)                             # selected course
        sel = _deg(getattr(self, "_hdgBug", 0.0) or 0.0)          # selected heading (bug)
        white = QColor(self.fg_color)
        cyan = QColor(getattr(self, "heading_bug_color", "#00ffff"))
        crscol = self._course_pointer_color()

        W = self.width(); H = self.height()
        m = self.fontSize * 0.5
        bh = self.fontSize * 2.4
        if layout == "top_panel":
            # One sectioned panel across the top gutter, OUTSIDE the rose (Bill's
            # pick, 2026-08-02). The rose was shrunk/shifted down in resizeEvent.
            g = getattr(self, "_gutter", 0.0) or (H * 0.16)
            ph = g * 0.76
            pw = self.fontSize * 12.5
            px = W / 2.0 - pw / 2.0
            py = (g - ph) / 2.0
            # Tab drawn BEFORE the panel: the panel's own left border (drawn on
            # top, next) is what defines the crisp shared edge, so there is no
            # separate seam/stroke to align by hand (pyEfis#140).
            self._draw_source_tab(c, px, py, ph)
            self._draw_readout_panel(c, px, py, pw, ph, "h",
                [("HDG", sel, cyan), ("MAG", hdg, white), ("CRS", crs, crscol)])
        elif layout == "corners":
            # selected-heading (cyan) top-left, course (source) top-right; actual
            # heading read from the rose.
            self._draw_readout_box(c, m, m, "lt", "HDG", sel, cyan)
            self._draw_readout_box(c, W - m, m, "rt", "CRS", crs, crscol)
        elif layout == "split":
            # Actual-heading box ABOVE the rose (top gutter, outside), course +
            # selected heading in the bottom corners (Bill 2026-08-02).
            self._draw_readout_box(c, W / 2.0, m * 0.5, "ct", "MAG", hdg, white)
            self._draw_readout_box(c, m, H - m, "lb", "CRS", crs, crscol)
            self._draw_readout_box(c, W - m, H - m, "rb", "HDG", sel, cyan)

    def _draw_readout_panel(self, c, x, y, w, h, orientation, segments):
        """One sectioned readout panel (P5a iter4b): a single rounded container
        divided into equal cells, each a small label + degree value with hairline
        dividers. orientation 'v' stacks cells, 'h' rows them. Translucent fill
        for legibility over the map."""
        # Shared house style (helpers.READOUT_*): this panel is where the look
        # was established, and the tape readout boxes now draw through the same
        # primitive (P5c) so the two cannot drift.
        _panel_rect = QRectF(x, y, w, h)
        _panel_radius = self.fontSize * helpers.READOUT_RADIUS_RATIO
        self._draw_readout_shadow(c, _panel_rect, _panel_radius)
        _pen, _brush = helpers.draw_readout_panel(
            c, _panel_rect, _panel_radius,
            QColor(self.fg_color),
            pen_width=self.fontSize * helpers.READOUT_PEN_RATIO,
        )
        border = _pen.color()
        n = max(1, len(segments))
        # Labels: bolder + a touch larger so the cyan/magenta read true at small
        # sizes (Bill 2026-08-02: cyan HDG label read greenish when tiny).
        lf = QFont(self.font_family); lf.setPixelSize(max(9, int(self.fontSize * 0.64)))
        lf.setBold(True)
        vf = QFont(self.font_family); vf.setPixelSize(max(12, int(self.fontSize * 1.18)))
        for i, (label, value, color) in enumerate(segments):
            if orientation == "v":
                sx, sy, sw, sh = x, y + h * i / n, w, h / n
                if i > 0:
                    c.setPen(QPen(border))
                    c.drawLine(QLineF(x + w * 0.14, sy, x + w * 0.86, sy))
            else:
                sx, sy, sw, sh = x + w * i / n, y, w / n, h
                if i > 0:
                    c.setPen(QPen(border))
                    c.drawLine(QLineF(sx, y + h * 0.14, sx, y + h * 0.86))
            c.setFont(lf); c.setPen(QPen(QColor(color)))
            c.drawText(QRectF(sx, sy + sh * 0.12, sw, sh * 0.36),
                       int(Qt.AlignmentFlag.AlignCenter), label)
            c.setFont(vf); c.setPen(QPen(QColor(self.fg_color)))
            c.drawText(QRectF(sx, sy + sh * 0.40, sw, sh * 0.56),
                       int(Qt.AlignmentFlag.AlignCenter), value)

    def _draw_source_tab(self, c, px, py, ph):
        """Nav-source annunciation as a coloured tab hanging off the left edge
        of the HDG | MAG | CRS panel, `readout_layout: top_panel` only
        (pyEfis#140). Fill = active source colour (magenta GPS / green VLOC,
        `_source_color()`); text white, centred both axes. Height is the
        panel height less both corner radii -- the straight run of the
        panel's left edge -- so it sits a few pixels shorter than the panel
        top and bottom, which is what reads as a tab rather than a bolted-on
        box. Left corners rounded on the shared READOUT_RADIUS_RATIO token
        (clamped to half the tab height); right edge square and flush at
        `px`. The whole tab rect becomes the tap target (_source_label_rect;
        mousePressEvent cycles NAVSRC unchanged).

        Fit is not guaranteed at every shipped font_percent -- see
        docs/hsi_widget_spec.md sec 7.4. The panel is never moved or resized
        to make room; nothing here truncates the label to hide an overflow."""
        self._source_label_rect = None
        if not getattr(self, "source_label_enabled", True):
            return
        label = self._source_label()
        if not label:
            return
        rr = self.fontSize * helpers.READOUT_RADIUS_RATIO
        th = ph - 2.0 * rr
        if th <= 0:
            return
        tab_r = min(rr, th / 2.0)
        lf = QFont(self.font_family)
        lf.setPixelSize(int(self.fontSize))
        c.setFont(lf)
        fm = c.fontMetrics()
        pad = self.fontSize * 0.35
        tab_w = fm.horizontalAdvance(label) + 2.0 * pad
        top = py + rr
        right = px
        left = right - tab_w

        # Extend the fill a hair past the shared edge; the panel border,
        # drawn on top right after this call, paints over the sliver and
        # owns the crisp boundary -- avoids an anti-aliasing gap/seam between
        # two independently-stroked shapes without doubling the stroke.
        overlap = max(1.0, self.fontSize * helpers.READOUT_PEN_RATIO * 0.5)
        path = QPainterPath()
        path.moveTo(right + overlap, top)
        path.lineTo(left + tab_r, top)
        path.arcTo(left, top, tab_r * 2.0, tab_r * 2.0, 90, 90)
        path.lineTo(left, top + th - tab_r)
        path.arcTo(left, top + th - tab_r * 2.0, tab_r * 2.0, tab_r * 2.0, 180, 90)
        path.lineTo(right + overlap, top + th)
        path.closeSubpath()
        c.setPen(Qt.PenStyle.NoPen)
        c.setBrush(QBrush(self._source_color() or QColor(self.course_color)))
        c.drawPath(path)

        c.setPen(QPen(QColor(Qt.GlobalColor.white)))
        c.drawText(QRectF(left, top, tab_w, th),
                   int(Qt.AlignmentFlag.AlignCenter), label)
        self._source_label_rect = (left, top, tab_w, th)

    def _draw_flag(self, c, text, x, y):
        """Draw a red boxed warning flag centred at (x, y) (AC 25-11B: warnings
        red). Black fill keeps it legible over the compass card."""
        red = QColor(255, 0, 0)
        f = QFont(self.font_family)
        f.setBold(True)
        f.setPixelSize(int(self.fontSize))
        c.setFont(f)
        fm = c.fontMetrics()
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad = int(self.fontSize * 0.3)
        box = QRectF(x - tw / 2.0 - pad, y - th / 2.0 - pad,
                     tw + 2 * pad, th + 2 * pad)
        c.setBrush(QBrush(QColor(0, 0, 0)))
        c.setPen(QPen(red, max(2, int(self.fontSize * 0.12))))
        c.drawRect(box)
        c.setPen(QPen(red))
        c.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)

    def getHeading(self):
        return self._heading

    def setHeading(self, heading):
        if heading != self._heading:
            now = time.time()
            newheading = common.bounds(0, 360, heading)
            diff = newheading - self._heading
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360
            self._heading = newheading
            self.rotate(-diff)
            self.last_update_time = now

    def setHeadOld(self,old):
        self._HeadOld = old

    def setHeadBad(self,bad):
        self._HeadBad = bad

    def setHeadFail(self,fail):
        if fail != self._HeadFail:
            self._HeadFail = fail
            self.changeFail()
 
    heading = property(getHeading, setHeading)

    def isOld(self):
        return self._GsiOld    or self._GsiBad\
            or self._CdiOld    or self._CdiBad\
            or self._HeadOld   or self._HeadBad\
            or self._CourseOld or self._CourseBad

    def isFail(self):
        return self._GsiFail\
            or self._CdiFail\
            or self._HeadBad\
            or self._CourseBad

    def changeFail(self):
        if self.isFail():
            for l in self.labels:
                l.setOpacity(0)
        else:
            for l in self.labels:
                l.setOpacity(1)

    def getCoursePointer(self):
        return self._courseSelect

    def setCoursePointer(self, course):
        if course != self._courseSelect:
            self._courseSelect = common.bounds(0, 360, course)
            if self.course_pointer is not None:
                self.course_pointer.setPolygon(self.course_pointer_polygon())
            if self.isVisible():
                self.update()

    coursePointer = property(getCoursePointer, setCoursePointer)

    def _source_color(self):
        """Active-source colour for the course pointer and CDI/GSI when
        source_auto_color is on: course_color (magenta) for a GPS source,
        vloc_color (green) for a VOR/LOC source. Returns None when auto-colouring
        is off or NAVSRC is unavailable, so callers fall back to the static
        per-element colour."""
        if not getattr(self, "source_auto_color", False):
            return None
        if self._navsrc is None:
            return None
        # NAVSRC 2 = GPS (magenta); 0/1 = NAV1/NAV2 (green).
        if int(round(self._navsrc)) == 2:
            return QColor(self.course_color)
        return QColor(self.vloc_color)

    def _course_pointer_color(self):
        return self._source_color() or QColor(self.course_color)

    def setNavsrc(self, value):
        if value != self._navsrc:
            self._navsrc = value
            # Recolour the course pointer now; the CDI/GSI recolour on next paint.
            if getattr(self, "course_pointer", None) is not None:
                _cp = self._course_pointer_color()
                self.course_pointer.setPen(QPen(_cp))
                self.course_pointer.setBrush(QBrush(_cp))
            if self.isVisible():
                self.update()

    def setNavtype(self, value):
        if value != self._navtype:
            self._navtype = value
            if self.isVisible():
                self.update()

    def setGsv(self, value):
        if value != self._gsv:
            self._gsv = value
            if self.isVisible():
                self.update()

    def setTofrom(self, value):
        if value != self._tofrom:
            self._tofrom = value
            if self.isVisible():
                self.update()

    # -- Bearing pointers (P5b.2) ------------------------------------------
    def _setBrg(self, n, value):
        v = common.bounds(0, 360, value)
        if v != self._brg[n]:
            self._brg[n] = v
            if self.isVisible():
                self.update()

    def _setBrgOld(self, n, old):
        self._brgOld[n] = old
        if self.isVisible():
            self.update()

    def _setBrgBad(self, n, bad):
        self._brgBad[n] = bad
        if self.isVisible():
            self.update()

    def _setBrgFail(self, n, fail):
        self._brgFail[n] = fail
        if self.isVisible():
            self.update()

    def _setBrgSrc(self, n, value):
        if value != self._brgSrc[n]:
            self._brgSrc[n] = value
            if self.isVisible():
                self.update()

    def _bearing_angle_deg(self, n):
        """On-screen needle angle for pointer n on the heading-up card:
        (BRGn - heading), normalised to [0, 360). 0 = straight up (lubber)."""
        return (self._brg[n] - self._heading) % 360.0

    def _bearing_color(self, n):
        """Source colour for pointer n (HSI-COLOR-001/-002): magenta for GPS,
        green (vloc_color) for a VOR, the generic bearing_color when the source
        is unknown."""
        src = self._brgSrc[n]
        if src is None:
            return QColor(self.bearing_color)
        s = int(round(src))
        if s == 2:                                  # GPS
            return QColor(self.course_color)
        if s in (0, 1):                             # VOR1 / VOR2
            return QColor(self.vloc_color)
        return QColor(self.bearing_color)

    def _bearing_visible(self, n):
        """A bearing needle shows only when enabled, its key exists, the heading
        is valid (HSI-ANN-001 -- a bearing is heading-referenced), and its own
        BRGn is valid (HSI-FAIL-001)."""
        if not getattr(self, "bearing%d_enabled" % n, False):
            return False
        if self.brgdb[n] is None:
            return False
        if self._HeadFail or self._HeadBad:
            return False
        if self._brgOld[n] or self._brgBad[n] or self._brgFail[n]:
            return False
        return True

    def _draw_bearing_needle(self, c, n):
        """Draw the RMI bearing needle for pointer n in viewport space, rotated
        to (BRGn - heading). Head (arrowhead) points at the station; a centre gap
        keeps the ownship symbol clear; the tail is the reciprocal. Pointer 1 is
        a single bar, pointer 2 a double bar (classic RMI). Source-coloured."""
        color = self._bearing_color(n)
        ang = self._bearing_angle_deg(n) * math.pi / 180.0
        ca = math.cos(ang)
        sa = math.sin(ang)

        def _p(lx, ly):
            return QPointF(self.cx + lx * ca - ly * sa, self.cy + ly * ca + lx * sa)

        ho = self.r * 0.80          # head tip radius (short of the numerals)
        to = self.r * 0.80          # tail end radius
        inner = self.r * 0.24       # centre gap half-length
        arr = self.tickSize         # arrowhead size
        w = max(2, int(getattr(self, "needle_width", 3)))
        pen = QPen(color, w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        c.setPen(pen)
        c.setBrush(QBrush(color))
        offs = [0.0] if n == 1 else [-arr * 0.35, arr * 0.35]
        for off in offs:
            c.drawLine(_p(off, -inner), _p(off, -ho + arr))     # head shaft
            c.drawLine(_p(off, inner), _p(off, to))             # tail shaft
        # Single centred arrowhead at the head end (points to the station).
        c.drawPolygon(QPolygonF([_p(0.0, -ho), _p(arr * 0.55, -ho + arr),
                                 _p(-arr * 0.55, -ho + arr)]))

    def _bearing_src_label(self, n):
        """Bearing-source annunciation text for pointer n: "1 GPS" / "2 VOR1"
        etc. The leading digit ties the label to its needle (single/double bar).
        Empty when the source is unknown."""
        src = self._brgSrc[n]
        if src is None:
            return ""
        name = {0: "VOR1", 1: "VOR2", 2: "GPS"}.get(int(round(src)), "")
        if not name:
            return ""
        return "%d %s" % (n, name)

    # -- Arc orientation mode (P5b.3) --------------------------------------
    # The forward heading sector (+/- ARC_HALF_DEG, so 120 deg total) is spread
    # LINEARLY across the widget width at an expanded angular scale, bowed down
    # at the edges so it reads as a compass arc. Every heading-referenced element
    # (ticks, numerals, heading bug, track diamond, bearing needles, course/CDI)
    # is placed through _arc_band_point / _arc_in_sector so they all share the one
    # scale. This is a SEPARATE paint path -- it never touches the rose bake or
    # the view rotation, so the north_up/heading_up/track_up rose is unchanged.
    #
    # DECISION (pyEfis#133, 2026-08-23): this widget is an HSI, and its arc
    # mode's CDI stays COURSE-BOUND -- the deviation bar and dots are drawn at
    # ownship, perpendicular to the course line, so the whole CDI rotates with
    # the course pointer as heading/course change. That is _draw_arc_course's
    # behaviour today and it is staying. Precedent: Garmin G1000/G3X Touch PFD
    # HSI, both of which keep the CDI bound to the course arrow in ARC mode.
    #
    # This was flagged because it borrows the arc idiom from transport-category
    # Navigation Displays (Boeing 737 ND, Airbus ND), which instead show a
    # SCREEN-FIXED deviation scale at the display edge -- confirmed against
    # authoritative 737 avionics material (see #133). That is a genuinely
    # different idiom, not a variant of this one, so it does not belong here:
    # it is scoped to a separate Navigation Display mode on the moving-map
    # instrument (pyEfis#134), which this HSI widget does not implement and
    # must not grow toward. If a screen-fixed deviation scale is ever wanted
    # on THIS widget, that is a reopening of #133, not a tweak to arc mode.
    ARC_HALF_DEG = 60.0

    @staticmethod
    def _rel_angle(a, b):
        """Shortest signed (a - b) in (-180, 180]."""
        d = (a - b) % 360.0
        if d > 180.0:
            d -= 360.0
        return d

    def _arc_params(self):
        """Arc screen geometry, cached by (w, h, fontSize):
        (cx, top_y, own_y, half_w, sag). The forward +/-ARC_HALF_DEG sector maps
        linearly onto x in [cx-half_w, cx+half_w] (so the scale is half_w /
        ARC_HALF_DEG px per heading degree -- larger than the full rose's
        r*pi/180, the expansion), and the band bows down by sag*frac^2."""
        w = self.width()
        h = self.height()
        key = (w, h, float(self.fontSize))
        cached = getattr(self, "_arc_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        cx = w / 2.0
        half_w = 0.94 * cx
        top_y = self.fontSize * 1.7          # band y at the lubber (rel=0)
        # Clear the top-panel/split integral readouts: resizeEvent set a top
        # gutter for those layouts, so drop the band below it.
        g = getattr(self, "_gutter", 0.0) or 0.0
        if g > 0.0:
            top_y = g + self.fontSize * 0.9
        sag = min(h * 0.16, half_w * 0.34)   # downward bow at the sector edges
        own_y = h * 0.82                      # ownship near lower centre
        params = (cx, top_y, own_y, half_w, sag)
        self._arc_cache = (key, params)
        return params

    def _arc_scale(self):
        """The arc angular-scale factor: screen px per heading degree along the
        band. This is the 'new scale factor' arc mode adds; it exceeds the full
        rose's edge scale (r * pi/180) so the forward sector reads expanded."""
        cx, top_y, own_y, half_w, sag = self._arc_params()
        return half_w / self.ARC_HALF_DEG

    def _arc_in_sector(self, bearing):
        """True when `bearing` falls inside the shown forward sector."""
        return abs(self._rel_angle(bearing, self._heading)) <= self.ARC_HALF_DEG + 1e-9

    def _arc_band_point(self, bearing):
        """Screen (x, y) on the compass band for a world `bearing` at the current
        heading. rel=0 (straight ahead) sits at the top lubber (cx, top_y);
        +rel goes right, -rel left, linearly; y bows down by sag*frac^2."""
        cx, top_y, own_y, half_w, sag = self._arc_params()
        frac = self._rel_angle(bearing, self._heading) / self.ARC_HALF_DEG
        return cx + frac * half_w, top_y + sag * frac * frac

    def _paint_arc(self, event):
        """Expanded forward-arc HSI. A decluttered forward-sector compass, drawn
        directly in viewport space (no rose bake, no view rotation)."""
        c = QPainter(self.viewport())
        c.setRenderHint(QPainter.RenderHint.Antialiasing)
        c.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cx, top_y, own_y, half_w, sag = self._arc_params()
        fg = QColor(self.fg_color)
        fail = self.isFail()

        # 1. Compass band ticks (every 5 deg in-sector), weight/length hierarchy
        # matching the rose; each tick fans slightly toward ownship.
        base = int(round(self._heading))
        span = int(self.ARC_HALF_DEG) + 5
        for d in range(base - span, base + span + 1, 5):
            cnt = d % 360
            if not self._arc_in_sector(cnt):
                continue
            if cnt % 90 == 0:
                tlen = self.tickSize * 1.25; tw = self.fontSize * 0.055
            elif cnt % 30 == 0:
                tlen = self.tickSize * 1.15; tw = self.fontSize * 0.045
            elif cnt % 10 == 0:
                tlen = self.tickSize; tw = self.fontSize * 0.03
            else:
                tlen = self.tickSize * 0.5; tw = self.fontSize * 0.018
            bx, by = self._arc_band_point(cnt)
            dx = cx - bx; dy = own_y - by
            dl = math.hypot(dx, dy) or 1.0
            ix = bx + dx / dl * tlen
            iy = by + dy / dl * tlen
            c.setPen(QPen(fg, max(1.0, tw)))
            c.drawLine(QLineF(bx, by, ix, iy))

        # 2. Numerals (screen-upright) at 30-deg, cardinal letters at 90-deg,
        # just inside the band. Hidden on fail (matches the rose label opacity).
        if not fail:
            nsize = max(10, int(self.fontSize * getattr(self, "numeral_scale", 1.5)))
            nf = QFont(self.font_family); nf.setPixelSize(nsize)
            c.setFont(nf); c.setPen(QPen(fg))
            _bw = nsize * 3.0; _bh = nsize * 1.6
            for d in range(base - span, base + span + 1, 5):
                cnt = d % 360
                if cnt % 30 != 0 or not self._arc_in_sector(cnt):
                    continue
                txt = self.cardinal[cnt // 90] if cnt % 90 == 0 else str(cnt // 10)
                bx, by = self._arc_band_point(cnt)
                dx = cx - bx; dy = own_y - by
                dl = math.hypot(dx, dy) or 1.0
                lx = bx + dx / dl * (self.tickSize * 1.4 + nsize * 0.7)
                ly = by + dy / dl * (self.tickSize * 1.4 + nsize * 0.7)
                c.drawText(QRectF(lx - _bw / 2, ly - _bh / 2, _bw, _bh),
                           int(Qt.AlignmentFlag.AlignCenter), txt)

        # 3. Top lubber triangle at (cx, top_y), pointing UP at the band.
        _lub = self.fontSize * 0.7
        lubber = QPolygonF([
            QPointF(cx - _lub * 0.55, top_y - _lub),
            QPointF(cx + _lub * 0.55, top_y - _lub),
            QPointF(cx, top_y + _lub * 0.35),
        ])
        c.setPen(QPen(fg, max(1, int(self.fontSize * 0.05))))
        c.setBrush(QBrush(fg))
        c.drawPolygon(lubber)

        # 4. Bearing needles (P5b.2) + course/CDI, drawn from ownship toward the
        # band. Bearing needles first so the deviation bar is never overridden.
        for _n in (1, 2):
            if self._bearing_visible(_n):
                self._draw_arc_bearing_needle(c, _n, cx, own_y)

        self._showCDI = self.cdi_enabled and not (self._CdiOld or self._CdiBad)
        self._showGSI = self.gsi_enabled and (self._gsv is None or self._gsv >= 0.5) \
            and not (self._GsiOld or self._GsiBad or self._GsiFail)
        if self.cdi_enabled or self.gsi_enabled:
            self._draw_arc_course(c, cx, own_y)

        # 5. Heading bug + track diamond as band markers (in-sector only).
        if getattr(self, "heading_bug_enabled", False) and not (self._HeadFail or self._HeadBad):
            if self._arc_in_sector(self._hdgBug):
                self._draw_arc_band_marker(c, self._hdgBug,
                                           QColor(self.heading_bug_color), "bug")
        if self._track_visible() and self._arc_in_sector(self._track):
            self._draw_arc_band_marker(c, self._track, QColor(self.track_color), "diamond")

        # 6. Ownship symbol at (cx, own_y), pointing up.
        _sym = getattr(self, "center_symbol", "aircraft")
        if _sym != "none":
            s = min(half_w, own_y - top_y) * 0.10
            ac_pen = QPen(fg, max(1.5, self.fontSize * 0.05))
            ac_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            ac_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            c.setPen(ac_pen); c.setBrush(QColor(Qt.GlobalColor.transparent))
            c.drawLine(QLineF(cx, own_y - s, cx, own_y + s))
            c.drawLine(QLineF(cx - s, own_y, cx + s, own_y))
            c.drawLine(QLineF(cx - s * 0.4, own_y + s * 0.7, cx + s * 0.4, own_y + s * 0.7))

        # 7. Nav-source + bearing-source labels (same annunciations + tap targets
        # as the rose path), then the integral readouts.
        self._draw_arc_source_labels(c)
        self._draw_readouts(c)

        # 8. Warning flags (same rules as the rose path).
        self._showHdgFlag = self._HeadFail or self._HeadBad
        if self._showHdgFlag:
            self._draw_flag(c, "HDG", cx, top_y)
        self._showNavFlag = self._CdiFail or self._CdiBad
        if self._showNavFlag:
            self._draw_flag(c, "NAV", cx, own_y - self.fontSize * 2.0)
        self._showGsFlag = (self.gsi_enabled and self._gsv is not None
                            and self._gsv >= 0.5 and (self._GsiFail or self._GsiBad))
        if self._showGsFlag:
            self._draw_flag(c, "GS", self.width() - self.fontSize * 1.5, own_y)

    def _draw_arc_bearing_needle(self, c, n, ox, oy):
        """Arc bearing needle: a line from ownship (ox, oy) to the band point of
        BRGn with an arrowhead at the band; hidden when out of the forward
        sector (forward clip). Single bar for pointer 1, double for pointer 2."""
        if not self._arc_in_sector(self._brg[n]):
            return
        color = self._bearing_color(n)
        bx, by = self._arc_band_point(self._brg[n])
        dx = bx - ox; dy = by - oy
        dl = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dl, dy / dl
        px, py = -uy, ux                       # unit perpendicular
        w = max(2, int(getattr(self, "needle_width", 3)))
        pen = QPen(color, w); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        c.setPen(pen); c.setBrush(QBrush(color))
        gap = min(dl * 0.28, self.tickSize * 2.0)   # centre gap past the ownship
        arr = self.tickSize
        offs = [0.0] if n == 1 else [-arr * 0.35, arr * 0.35]
        for off in offs:
            sx = ox + px * off; sy = oy + py * off
            c.drawLine(QLineF(sx + ux * gap, sy + uy * gap,
                              bx - ux * arr, by - uy * arr))
        tip = QPointF(bx, by)
        l = QPointF(bx - ux * arr + px * arr * 0.55, by - uy * arr + py * arr * 0.55)
        r = QPointF(bx - ux * arr - px * arr * 0.55, by - uy * arr - py * arr * 0.55)
        c.drawPolygon(QPolygonF([tip, l, r]))

    def _draw_arc_course(self, c, ox, oy):
        """Arc course pointer + lateral CDI: the pointer runs from ownship toward
        the COURSE band point (when in sector); the deviation dots and CDI bar sit
        at ownship, perpendicular to the course line, so the CDI angle tracks the
        arc scale. GS is the screen-fixed right-side scale, shared with the rose.
        Course-bound by decision, not by default -- see pyEfis#133; a
        screen-fixed lateral scale is the Navigation Display idiom and belongs
        on the moving-map ND mode (pyEfis#134), not here."""
        if self.cdi_enabled and self._arc_in_sector(self._courseSelect):
            bx, by = self._arc_band_point(self._courseSelect)
            dx = bx - ox; dy = by - oy
            dl = math.hypot(dx, dy) or 1.0
            ux, uy = dx / dl, dy / dl
            px, py = -uy, ux
            bar = min(self._arc_params()[3], oy - self._arc_params()[1]) * 0.22
            # deviation dots
            c.setPen(QPen(QColor(self.fg_color))); c.setBrush(QBrush(QColor(self.fg_color)))
            dotr = max(1.5, self.tickSize * 0.16)
            for dev in (-1.0, -2.0/3.0, -1.0/3.0, 1.0/3.0, 2.0/3.0, 1.0):
                c.drawEllipse(QPointF(ox + px * dev * bar, oy + py * dev * bar), dotr, dotr)
            cpc = self._course_pointer_color()
            cw = max(2, int(getattr(self, "needle_width", 3)))
            c.setPen(QPen(cpc, cw)); c.setBrush(QBrush(cpc))
            arr = self.tickSize
            c.drawLine(QLineF(ox + ux * bar, oy + uy * bar, bx - ux * arr, by - uy * arr))
            tip = QPointF(bx, by)
            l = QPointF(bx - ux * arr + px * arr * 0.55, by - uy * arr + py * arr * 0.55)
            r = QPointF(bx - ux * arr - px * arr * 0.55, by - uy * arr - py * arr * 0.55)
            c.drawPolygon(QPolygonF([tip, l, r]))
            if self._showCDI:
                off = self._courseDeviation * bar
                c.drawLine(QLineF(ox + px * off - ux * bar, oy + py * off - uy * bar,
                                  ox + px * off + ux * bar, oy + py * off + uy * bar))
        if self.gsi_enabled and (self._gsv is None or self._gsv >= 0.5):
            gx = self.width() - self.fontSize * 1.5
            gy0 = self._arc_params()[2]                 # own_y
            grange = min(self.width(), self.height()) * 0.16
            c.setPen(QPen(QColor(self.fg_color))); c.setBrush(QBrush(QColor(self.fg_color)))
            gdot = max(1.5, self.tickSize * 0.16)
            c.drawLine(QLineF(gx - self.tickSize * 0.55, gy0, gx + self.tickSize * 0.55, gy0))
            for dev in (-1.0, -0.5, 0.5, 1.0):
                c.drawEllipse(QPointF(gx, gy0 - dev * grange), gdot, gdot)
            if self._showGSI:
                gsc = self._source_color() or QColor(self.needle_color)
                c.setPen(QPen(gsc)); c.setBrush(QBrush(gsc))
                gy = gy0 - self._glideSlopeIndicator * grange
                ds = self.tickSize * 0.6
                c.drawPolygon(QPolygonF([QPointF(gx, gy - ds), QPointF(gx + ds, gy),
                                         QPointF(gx, gy + ds), QPointF(gx - ds, gy)]))

    def _draw_arc_band_marker(self, c, bearing, color, shape):
        """A small marker (heading 'bug' or track 'diamond') on the arc band at
        `bearing`."""
        bx, by = self._arc_band_point(bearing)
        s = self.tickSize * 0.55
        c.setPen(QPen(color)); c.setBrush(QBrush(color))
        if shape == "diamond":
            c.drawPolygon(QPolygonF([QPointF(bx, by - s), QPointF(bx + s, by),
                                     QPointF(bx, by + s), QPointF(bx - s, by)]))
        else:                                            # heading bug (notched)
            w = s * 1.1; h = s * 1.6
            c.drawPolygon(QPolygonF([
                QPointF(bx - w, by + h), QPointF(bx - w, by),
                QPointF(bx - w * 0.35, by), QPointF(bx - w * 0.35, by + h * 0.5),
                QPointF(bx + w * 0.35, by + h * 0.5), QPointF(bx + w * 0.35, by),
                QPointF(bx + w, by), QPointF(bx + w, by + h)]))

    def _draw_arc_source_labels(self, c):
        """Nav-source annunciation (top-left, unless `readout_layout: top_panel`
        draws it as a tab via _draw_source_tab -- pyEfis#140) + per-pointer
        bearing-source labels (bottom corners), with the same tap targets as
        the rose path."""
        self._source_label_rect = None
        if getattr(self, "readout_layout", "top_panel") != "top_panel" \
                and getattr(self, "source_label_enabled", True):
            label = self._source_label()
            if label:
                c.setPen(QPen(self._source_color() or QColor(self.course_color)))
                lf = QFont(self.font_family); lf.setPixelSize(int(self.fontSize))
                c.setFont(lf)
                lx = qRound(self.width() * 0.03); ly = qRound(self.fontSize * 1.2)
                c.drawText(lx, ly, label)
                fm = c.fontMetrics(); pad = int(self.fontSize * 0.5)
                self._source_label_rect = (lx - pad, ly - fm.ascent() - pad,
                                           fm.horizontalAdvance(label) + 2 * pad,
                                           fm.height() + 2 * pad)
        self._brg_label_rect = {1: None, 2: None}
        for _n in (1, 2):
            if not getattr(self, "bearing%d_enabled" % _n, False):
                continue
            if self.brgdb[_n] is None and self.brgsrcdb[_n] is None:
                continue
            invalid = (self.brgdb[_n] is None or self._brgOld[_n]
                       or self._brgBad[_n] or self._brgFail[_n])
            # A valid pointer clipped outside the forward sector draws no
            # needle (_draw_arc_bearing_needle); its label must not outlive
            # it, or the annunciation reads as "on screen" when it is not.
            # Invalid pointers keep the label regardless of sector -- the
            # failure is real regardless of where the stale bearing points.
            if not invalid and not self._arc_in_sector(self._brg[_n]):
                continue
            txt = self._bearing_src_label(_n)
            if not txt:
                continue
            if invalid:
                txt = txt + " X"
            lf = QFont(self.font_family); lf.setPixelSize(int(self.fontSize * 0.85))
            c.setFont(lf); fm = c.fontMetrics()
            tw = fm.horizontalAdvance(txt); th = fm.height()
            _bc = QColor(255, 150, 0) if invalid else self._bearing_color(_n)
            c.setPen(QPen(_bc))
            ly = qRound(self.height() - self.fontSize * 0.5)
            lx = qRound(self.width() * 0.03) if _n == 1 else qRound(self.width() * 0.97 - tw)
            c.drawText(lx, ly, txt)
            pad = int(self.fontSize * 0.5)
            self._brg_label_rect[_n] = (lx - pad, ly - fm.ascent() - pad,
                                        tw + 2 * pad, th + 2 * pad)

    def _cycle_bearing_src(self, n):
        """Cycle pointer n's source selector VOR1 -> VOR2 -> GPS -> VOR1
        (BRGnSRC 0/1/2), writing the FIX key so the fix-gateway select re-routes
        the canonical BRGn (one-key-one-writer)."""
        if self.brgsrcdb[n] is None:
            return
        cur = int(round(self._brgSrc[n])) if self._brgSrc[n] is not None else 2
        fix.db.set_value("BRG%dSRC" % n, float((cur + 1) % 3))

    def mousePressEvent(self, event):
        # Tapping the nav-source annunciation cycles the source: GPS -> NAV1 ->
        # NAV2 -> GPS (NAVSRC 2/0/1). Anywhere else, default handling.
        r = getattr(self, "_source_label_rect", None)
        if r is not None and getattr(self, "navsrcdb", None) is not None:
            px, py = event.pos().x(), event.pos().y()
            if r[0] <= px <= r[0] + r[2] and r[1] <= py <= r[1] + r[3]:
                cur = int(round(self._navsrc)) if self._navsrc is not None else 2
                fix.db.set_value("NAVSRC", float((cur + 1) % 3))
                event.accept()
                return
        # Tapping a bearing-source label cycles that pointer's source (mirrors
        # the nav-source tap; BRGnSRC 0->1->2->0).
        br = getattr(self, "_brg_label_rect", None) or {}
        px, py = event.pos().x(), event.pos().y()
        for _n in (1, 2):
            rr = br.get(_n)
            if rr is not None and rr[0] <= px <= rr[0] + rr[2] \
                    and rr[1] <= py <= rr[1] + rr[3]:
                self._cycle_bearing_src(_n)
                event.accept()
                return
        super(HSI, self).mousePressEvent(event)

    def _source_label(self):
        """Nav-source annunciation text: "GPS" for a GPS source, "VOR{n}" /
        "LOC{n}" when NAVTYPE identifies the NAV radio, else "VLOC{n}" from NAVSRC
        alone. Empty when no source is available."""
        if self._navsrc is None:
            return ""
        src = int(round(self._navsrc))
        if src == 2:
            return "GPS"
        slot = src + 1                          # NAVSRC 0->NAV1, 1->NAV2
        nt = None if self._navtype is None else int(round(self._navtype))
        if nt == 1:
            return f"VOR{slot}"
        if nt in (2, 3):
            return f"LOC{slot}"
        return f"VLOC{slot}"

    def setCourseOld(self,old):
        self._CourseOld = old

    def setCourseBad(self,bad):
        self._CourseBad = bad

    def setCourseFail(self,fail):
        if fail != self._CourseFail:
            self._CourseFail = fail
            self.changeFail()

    def getCdi(self):
        return self._courseDeviation

    def setCdi(self, cdi):
        if cdi != self._courseDeviation:
            self._courseDeviation = cdi
            if self.isVisible(): 
                self.update()

    def setCdiOld(self, old):
        if self.cdi_enabled:
            self._CdiOld = old
            if self.isVisible():
                self.update()

    def setCdiBad(self, bad):
        if self.cdi_enabled:
            self._CdiBad = bad
            if self.isVisible():
                self.update()

    def setCdiFail(self, fail):
        if self.cdi_enabled:
            if fail != self._CdiFail:
                self._CdiFail = fail
                self.changeFail()


    cdi = property(getCdi, setCdi)

    def getGsi(self):
        return self._glideSlopeIndicator

    def setGsi(self, gsi):
        if gsi != self._glideSlopeIndicator:
            self._glideSlopeIndicator = gsi
            if self.isVisible(): self.update()

    gsi = property(getGsi, setGsi)

    def setGsiOld(self, old):
        if self.gsi_enabled:
            self._GsiOld = old
            if self.isVisible():
                self.update()

    def setGsiBad(self, bad):
        if self.gsi_enabled:
            self._GsiBad = bad
            if self.isVisible():
                self.update()

    def setGsiFail(self, fail):
        if self.gsi_enabled:
            if fail != self._GsiFail:
                self._GsiFail = fail
                self.changeFail()


    # We don't want this responding to keystrokes
    def keyPressEvent(self, event):
        pass

    # Don't want it acting with the mouse scroll wheel either
    def wheelEvent(self, event):
        pass

    def showEvent(self, event):
        self.update()


class HeadingDisplay(QWidget):
    def __init__(self, parent=None, fg_color="#aaaaaa", bg_color="#000000", bg_opacity=100, font_family="DejaVu Sans Condensed" ):
        super(HeadingDisplay, self).__init__(parent)
        self.font_family = font_family
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fg_color = fg_color
        self.bg_color = bg_color
        # Background-fill opacity, percent: 100 = solid box (default), 0 = fully
        # transparent so whatever is behind the box (e.g. the SVS/PFD) shows
        # through. The widget area itself is made transparent so the paintEvent
        # fill alpha is what controls the look.
        self.bg_opacity = bg_opacity
        self.setStyleSheet("background: transparent")

        self._Old = True
        self._Bad = True
        self._Fail = True

        self.item = fix.db.get_item("HEAD")
        self.item.valueChanged[float].connect(self.setHeading)
        self.item.failChanged[bool].connect(self.setFail)
        self.item.badChanged[bool].connect(self.setBad)
        self.item.oldChanged[bool].connect(self.setOld)
        self.setOld(self.item.old)
        self.setBad(self.item.bad)
        self.setFail(self.item.fail)

        self._heading = self.item.value

        self.font = QFont(self.font_family)
        self.font.setBold(True)
        # Include the degree sign so the font is sized to the actual content
        # ("030°"), not three bare digits — otherwise the trailing ° pushes the
        # centred text tight against the box edges.
        self.font_mask = "999°"
        self.font_percent = 0.80
        self.font_size = helpers.fit_to_mask(self.width()*self.font_percent ,self.height()*self.font_percent,self.font_mask,self.font_family)
        self.font.setPointSizeF(self.font_size)

    def resizeEvent(self, event):
        self.font_size = helpers.fit_to_mask(self.width()*self.font_percent ,self.height()*self.font_percent,self.font_mask,self.font_family)
        self.font.setPointSizeF(self.font_size)

    def paintEvent(self, event):
        self.font.setPointSizeF(self.font_size)
        c = QPainter(self)
        compassPen = QPen(QColor(self.fg_color))
        bg = QColor(self.bg_color)
        try:
            bg.setAlphaF(max(0.0, min(1.0, float(self.bg_opacity) / 100.0)))
        except (TypeError, ValueError):
            pass
        compassBrush = QBrush(bg)
        c.setPen(compassPen)
        c.setBrush(compassBrush)
        c.setFont(self.font)
        tr = QRectF(0, 0, self.width()-1, self.height()-1)
        c.drawRect(tr)
        if self._Fail:
            heading_text = "XXX"
            c.setBrush(QBrush(QColor(Qt.GlobalColor.red)))
            c.setPen(QPen(QColor(Qt.GlobalColor.red)))
        elif self._Bad:
            heading_text = ""
            c.setBrush(QBrush(QColor(255, 150, 0)))
            c.setPen(QPen(QColor(255, 150, 0)))
        elif self._Old:
            heading_text = ""
            c.setBrush(QBrush(QColor(255, 150, 0)))
            c.setPen(QPen(QColor(255, 150, 0)))
        else:
            heading_text = self._fmt_heading(self._heading)

        c.drawText(tr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, heading_text)

    @staticmethod
    def _fmt_heading(value):
        """Heading as three zero-padded digits with a trailing degree sign:
        3 -> "003°", 30 -> "030°", 360/0 -> "000°"."""
        return f"{int(value) % 360:03d}°"

    def getHeading(self):
        return self._heading

    def setHeading(self, heading):
        if heading != self._heading:
            self._heading = common.bounds(0, 360, heading)
            if self.isVisible(): self.update()

    heading = property(getHeading, setHeading)

    def setFail(self, fail):
        self._Fail = fail
        self.repaint()

    def setOld(self, old):
        self._Old = old
        self.repaint()

    def setBad(self, bad):
        self._Bad = bad
        self.repaint()

    def showEvent(self, event):
        self.update()

class DG_Tape(QGraphicsView):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed"):
        super(DG_Tape, self).__init__(parent)
        self.setStyleSheet("border: 0px")
        self.font_family = font_family
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fontsize = 20
        self._heading = 1
        self._headingSelect = 1
        self._courseSelect = 1
        self._courseDevation = 1
        self.cardinal = ["N", "E", "S", "W", "N"]

        self.item = fix.db.get_item("HEAD", True)
        self.item.valueChanged[float].connect(self.setHeading)
        self._heading = self.item.value

        # Heading-invalid annunciation (AC 23.1311-1C sec 8.6.a): a lost/stale
        # heading must be flagged, not scrolled as a frozen tape (loss of
        # direction reduces the pilot's capability; governing "no misleading
        # info" principle).
        self._fail = self.item.fail
        self._old = self.item.old
        self._bad = self.item.bad
        self.item.failChanged[bool].connect(self.setFail)
        self.item.oldChanged[bool].connect(self.setOld)
        self.item.badChanged[bool].connect(self.setBad)

        self.dpp = 10
    def resizeEvent(self, event):
        w = self.width()
        h = self.height()

        compassPen = QPen(QColor(Qt.GlobalColor.white))
        compassPen.setWidth(2)

        headingPen = QPen(QColor(Qt.GlobalColor.red))
        headingPen.setWidth(8)

        f = QFont(self.font_family)
        f.setPixelSize(self.fontsize)

        self.scene = QGraphicsScene(0, 0, 5000, h)
        self.scene.addRect(0, 0, 5000, h,
                           QPen(QColor(Qt.GlobalColor.black)), QBrush(QColor(Qt.GlobalColor.black)))

        self.setScene(self.scene)

        for i in range(-50, 410, 5):
            if i % 10 == 0:
                self.scene.addLine((i * 10) + w / 2, 0, (i * 10) + w / 2, h / 2,
                                   compassPen)
                if i > 360:
                    t = self.scene.addText(str(i - 360))
                    t.setFont(f)
                    self.scene.setFont(f)
                    t.setDefaultTextColor(QColor(Qt.GlobalColor.white))
                    t.setX(((i * 10) + w / 2) - t.boundingRect().width() / 2)
                    t.setY(h - t.boundingRect().height())
                elif i < 1:
                    t = self.scene.addText(str(i + 360))
                    t.setFont(f)
                    self.scene.setFont(f)
                    t.setDefaultTextColor(QColor(Qt.GlobalColor.white))
                    t.setX(((i * 10) + w / 2) - t.boundingRect().width() / 2)
                    t.setY(h - t.boundingRect().height())
                else:
                    if i % 90 == 0:
                        t = self.scene.addText(self.cardinal[int(i / 90)])
                        t.setFont(f)
                        self.scene.setFont(f)
                        t.setDefaultTextColor(QColor(Qt.GlobalColor.cyan))
                        t.setX(((i * 10) + w / 2) - t.boundingRect().width() / 2)
                        t.setY(h - t.boundingRect().height())
                    else:
                        t = self.scene.addText(str(i))
                        t.setFont(f)
                        self.scene.setFont(f)
                        t.setDefaultTextColor(QColor(Qt.GlobalColor.white))
                        t.setX(((i * 10) + w / 2) - t.boundingRect().width() / 2)
                        t.setY(h - t.boundingRect().height())
            else:
                self.scene.addLine((i * 10) + w / 2, 0,
                                   (i * 10) + w / 2, h / 2 - 20,
                                    compassPen)

    def redraw(self):
        self.resetTransform()
        self.centerOn(self._heading * self.dpp + self.width() / 2,
                      self.height() / 2)

    def getHeading(self):
        return self._heading

    def setHeading(self, heading):
        if heading != self._heading:
            self._heading = heading
            self.redraw()

    heading = property(getHeading, setHeading)

    def setFail(self, fail):
        self._fail = fail
        self.viewport().update()

    def setOld(self, old):
        self._old = old
        self.viewport().update()

    def setBad(self, bad):
        self._bad = bad
        self.viewport().update()

    def paintEvent(self, event):
        super(DG_Tape, self).paintEvent(event)
        # Annunciate an invalid heading over the centre read window. fail -> red
        # XXX masking the reading (a frozen tape must not read as valid); old/bad
        # -> grey wash + amber HDG flag (degraded). Same convention as the boxed
        # HeadingDisplay and the other tapes.
        if not (self._fail or self._old or self._bad):
            return
        w = self.width()
        h = self.height()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._fail:
            color = QColor(Qt.GlobalColor.red)
            text = "XXX"
        else:                                   # old / bad -> degraded
            p.fillRect(self.viewport().rect(), QColor(128, 128, 128, 120))
            color = QColor(255, 150, 0)
            text = "HDG"
        bw = w * 0.34
        bh = h * 0.72
        rect = QRectF(w / 2 - bw / 2, h / 2 - bh / 2, bw, bh)
        if self._fail:
            p.fillRect(rect, QColor(Qt.GlobalColor.black))
        pen = QPen(color)
        pen.setWidth(max(2, qRound(h * 0.03)))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        f = QFont(self.font_family)
        f.setBold(True)
        f.setPixelSize(max(10, qRound(h * 0.4)))
        p.setFont(f)
        p.setPen(QPen(color))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def showEvent(self, event):
        self.redraw()

    # We don't want this responding to keystrokes
    def keyPressEvent(self, event):
        pass

    # Don't want it acting with the mouse scroll wheel either
    def wheelEvent(self, event):
        pass

