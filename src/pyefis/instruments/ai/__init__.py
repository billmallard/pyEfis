#  Copyright (c) 2013 Phil Birkelbach; 2018-2019 Garrett Herschleb
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

from PyQt6.QtGui import *
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *

import math
import time
import logging

import pyavtools.fix as fix
from pyefis import common
from pyefis.instruments.ai.svs import SVSRenderer, make_svs_item
from pyefis.instruments.ai.pose import PoseSource

log = logging.getLogger(__name__)

# TODO:
#   Check TAS quality and revert to turn rate indication
#   Fix quality indications
#   Add quality flags to indicate the actual failures
#   Remove internal assignments of database items.  Should be a normal
#      Qt widget and these things done externally.
#   Add configuration for bank angle tick sizes

class AI(QGraphicsView):
    def __init__(self, parent=None, font_percent=None, font_family="DejaVu Sans Condensed", show_fpm=True):
        super(AI, self).__init__(parent)
        self.myparent = parent
        self.font_family = font_family
        self.show_fpm = show_fpm
        # The following information is meant to be configurable from the screen
        # definition file
        self.font_percent = font_percent
        if self.font_percent:
            self.fontSize = qRound(self.width() * self.font_percent)
        else:
            self.fontSize = 30
        # Number of degrees shown from top to bottom. This sets
        # pixelsPerDeg = widget_height / pitchDegreesShown, which is
        # the SAME scale applied to the horizontal axis, so the AI's
        # effective horizontal FOV = widget_width * pitchDegreesShown
        # / widget_height. At the original 60 deg on a 5" 800x480
        # panel the HFOV came out to ~100 deg — about 2x the angular
        # spread of a typical avionics PFD's synthetic-vision view
        # (Garmin GI-275: ~50 deg; G1000 PFD: ~50-60 deg; X-Plane
        # cockpit view: 60-70 deg). Terrain and runways appeared
        # roughly half their natural size as a result.
        #
        # 30 puts HFOV at 50 deg on a 5:3 panel (800x480 -> 50 deg,
        # 1024x600 -> 51.2 deg) — matches the Garmin GI-275 SVS and
        # most G1000-class PFD synthetic-vision views. The pitch
        # ladder spreads out by 60/30 = 2x relative to the original,
        # which gives more screen-space per degree of pitch (more
        # readable, and matches the visible pitch range real PFDs
        # use).
        self.pitchDegreesShown = 30
        # Pitch tick mark configurations
        self.minorDiv = 1   # Degrees between minor divisions
        self.majorDiv = 5  # Degrees between major divisions
        self.numberedDiv = 10 # Degrees between numbered divisions
        # Line widths of the pitch tick marks
        self.minorDivWidth = 10
        self.majorDivWidth = 40
        self.numberedDivWidth = 50
        self.visiblePitchAngle = 15 # Amount of visible pitch angle marks
        self.pitchOpacity = 0.6
        # Bank angle tick indicators
        self.bankMarkSize = 10
        # Standard rate turn bank angle indicators.
        self.drawBankMarkers = True
        self.bankAngleRadius = None # Radius of the bank angle markings
        self.bankAngleMaximum = 25  # Largest bank angle that will be indicated
        # Fixed aircraft reference symbol (the "wings" the horizon moves
        # behind). style: "classic" (split wing bars + center dot) or
        # "garmin"/"gi275" (GI-275-style stepped wing bars + center
        # chevron). Set from the screen YAML options (aircraft_symbol,
        # symbol_color); applied by the screenbuilder factory.
        self.aircraft_symbol = "classic"
        self.symbol_color = "yellow"

        self.setStyleSheet("border: 0px")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # ------------------------------------------------------------------
        # Frame clock (plan P4). FIX value slots only STORE state; this
        # timer samples the interpolated pose at the display rate and
        # triggers the repaint. Decouples render cadence from gateway
        # burst patterns and bounds the main-thread CPU. Flag changes
        # (old/bad/fail) still repaint immediately — they are alerts.
        # ------------------------------------------------------------------
        self._pose = PoseSource()
        self._frame_dirty = True
        self._frame_last_pose = None
        self._frame_timer = QTimer(self)
        # Coarse timers (the default) have 5% slack on top of the
        # 15.6 ms Windows tick — at 33 ms intervals that reads as
        # ~47 ms frames. Precise typing keeps the cadence honest.
        self._frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_timer.timeout.connect(self._frame_tick)
        self.set_frame_rate(30.0)

        # Assume True until told otherwise
        self._AIOld = dict()
        self._AIBad = dict()
        self._AIFail = dict()
        for p in ['PITCH', 'ROLL','ALAT','TAS']:
            self._AIOld[p] = True
            self._AIBad[p] = True
            self._AIFail[p] = True
        pitch = fix.db.get_item("PITCH")
        pitch.valueChanged[float].connect(self.setPitchAngle)
        pitch.oldChanged[bool].connect(self.setAIOldPitch)
        pitch.badChanged[bool].connect(self.setAIBadPitch)
        pitch.failChanged[bool].connect(self.setAIFailPitch)
        self._AIOld['PITCH'] = pitch.old
        self._AIBad['PITCH'] = pitch.bad
        self._AIFail['PITCH'] = pitch.fail
        self._pitchAngle = pitch.value
        roll = fix.db.get_item("ROLL")
        roll.valueChanged[float].connect(self.setRollAngle)
        roll.oldChanged[bool].connect(self.setAIOldRoll)
        roll.badChanged[bool].connect(self.setAIBadRoll)
        roll.failChanged[bool].connect(self.setAIFailRoll)
        self._rollAngle = roll.value
        self._AIOld['ROLL'] = roll.old
        self._AIBad['ROLL'] = roll.bad
        self._AIFail['ROLL'] = roll.fail
        alat = fix.db.get_item("ALAT")
        alat.valueChanged[float].connect(self.setLateralAcceleration)
        alat.oldChanged[bool].connect(self.setAIOldLAcc)
        alat.badChanged[bool].connect(self.setAIBadLAcc)
        alat.failChanged[bool].connect(self.setAIFailLAcc)
        self._AIOld['ALAT'] = alat.old
        self._AIBad['ALAT'] = alat.bad
        self._AIFail['ALAT'] = alat.fail
        self._latAccel = alat.value
        tas = fix.db.get_item("TAS")
        tas.valueChanged[float].connect(self.setTrueAirspeed)
        tas.oldChanged[bool].connect(self.setAIOldTAS)
        tas.badChanged[bool].connect(self.setAIBadTAS)
        tas.failChanged[bool].connect(self.setAIFailTAS)
        self._AIOld['TAS'] = tas.old
        self._AIBad['TAS'] = tas.bad
        self._AIFail['TAS'] = tas.fail

        self._tas = tas.value

        # Flight Path Marker (GPS method): VS, GS, TRACK, HEAD.
        # Keys default to fail=True so that if any are missing from the FIX
        # database (e.g. gateway doesn't publish TRACK), _drawFPM stays
        # silently disabled rather than crashing.
        # VPATH (vertical flight path angle, deg) is preferred when the
        # data source can produce it directly (X-Plane publishes it via
        # idx 18 slot 3 as the same value its own FPM symbol uses).
        # When VPATH isn't published we fall back to atan2(VS, GS),
        # which is correct in steady state but lags VPATH during
        # transient descents — the FIX key still wires up cleanly via
        # the missing-key guard below.
        self._fpm_fail = {k: True for k in ('VS', 'GS', 'TRACK', 'HEAD', 'VPATH')}
        self._fpm_bad  = {k: False for k in ('VS', 'GS', 'TRACK', 'HEAD', 'VPATH')}
        self._fpm_vs    = 0.0
        self._fpm_gs    = 0.0
        self._fpm_track = 0.0
        self._fpm_head  = 0.0
        self._fpm_vpath = 0.0
        for key in ('VS', 'GS', 'TRACK', 'HEAD', 'VPATH'):
            try:
                _item = fix.db.get_item(key)
            except KeyError:
                log.warning(
                    f"AI: FIX key '{key}' not defined — Flight Path Marker disabled")
                continue
            _item.valueChanged[float].connect(lambda v, k=key: self._fpmValueChanged(k, v))
            _item.failChanged[bool].connect(lambda f, k=key: self._fpmFailChanged(k, f))
            _item.badChanged[bool].connect(lambda b, k=key: self._fpmBadChanged(k, b))
            self._fpm_fail[key] = _item.fail
            self._fpm_bad[key]  = _item.bad
            setattr(self, f'_fpm_{key.lower()}', _item.value)
            self._pose.set_fail(key, _item.fail)

        # Seed the pose source from the initial FIX values — the
        # valueChanged signals for anything set before this widget
        # was constructed have already fired and will not repeat
        # until the value changes again.
        self._pose.set_dynamics(gs_kt=self._fpm_gs,
                                track_deg=self._fpm_track,
                                vs_fpm=self._fpm_vs)

        # SVS position inputs: LAT, LONG, ALT (disabled by default; renderer
        # set via set_svs_config). Missing keys leave the SVS position at 0
        # and the renderer's ready gate will skip drawing if no tiles match.
        self._svs_lat  = 0.0
        self._svs_lon  = 0.0
        self._svs_alt  = 0.0
        self.svs: SVSRenderer | None = None
        for key, attr in (("LAT", "_svs_lat"), ("LONG", "_svs_lon"), ("ALT", "_svs_alt")):
            try:
                _item = fix.db.get_item(key)
            except KeyError:
                log.warning(
                    f"AI: FIX key '{key}' not defined — SVS will use 0.0 for {attr}")
                continue
            _item.valueChanged[float].connect(
                lambda v, k=key: self._positionValueChanged(k, v))
            setattr(self, attr, _item.value)
        if self._svs_lat or self._svs_lon:
            self._pose.set_position(self._svs_lat, self._svs_lon)
        if self._svs_alt:
            self._pose.set_altitude(self._svs_alt)

        # Magnetic variation. SVS does its geographic projection in
        # true-north coordinates, so it needs TRUE heading. HEAD is by
        # convention magnetic (so the HSI rose reads naturally). The
        # AI widget converts HEAD to TRUE at SVS call time as
        # ``HEAD - MAGVAR``. Positive MAGVAR = west variation (FAA
        # "West is best": MAG = TRUE + W_VAR). When MAGVAR isn't
        # published the correction is zero and the SVS sits with a
        # constant rotational offset equal to local variation — small
        # error in low-variation regions, larger near the magnetic
        # poles.
        self._magvar = 0.0
        try:
            _item = fix.db.get_item("MAGVAR")
            _item.valueChanged[float].connect(
                lambda v: (setattr(self, "_magvar", v),
                           setattr(self, "_frame_dirty", True)))
            self._magvar = _item.value
        except KeyError:
            log.warning(
                "AI: FIX key 'MAGVAR' not defined — SVS heading "
                "will be treated as true heading (no mag-var correction)")

        # We store all the pitch tick marks and text in a list so that
        # we can adjust the opacity of the items.
        self.pitchItems = []

    def _draw_aircraft_symbol(self, p, w, h):
        """Draw the fixed aircraft reference symbol into the static
        overlay. Style + colour come from self.aircraft_symbol /
        self.symbol_color (screen YAML options)."""
        cx, cy = w / 2.0, h / 2.0
        col = QColor(self.symbol_color)
        if not col.isValid():
            col = QColor(Qt.GlobalColor.yellow)
        p.setPen(QPen(QColor(Qt.GlobalColor.black), 1))
        p.setBrush(QBrush(col))
        style = str(getattr(self, "aircraft_symbol", "classic")).lower()
        if style in ("garmin", "gi275", "gi-275", "g1000"):
            # GI-275 / G1000 style: two tapered wing wedges — thick at
            # the inboard end by the boresight, tapering to the
            # outboard tips — flanking a small centre boresight circle.
            t = max(2.0, h * 0.006)
            gap = w * 0.03           # inboard tip half-gap from centre
            wing = w * 0.15          # wing length
            p.drawPolygon(QPolygonF([              # left wing
                QPointF(cx - gap, cy - 2.2 * t),
                QPointF(cx - gap, cy + 2.2 * t),
                QPointF(cx - gap - wing, cy + 0.8 * t),
                QPointF(cx - gap - wing, cy - 0.4 * t)]))
            p.drawPolygon(QPolygonF([              # right wing (mirror)
                QPointF(cx + gap, cy - 2.2 * t),
                QPointF(cx + gap, cy + 2.2 * t),
                QPointF(cx + gap + wing, cy + 0.8 * t),
                QPointF(cx + gap + wing, cy - 0.4 * t)]))
            # Centre boresight: open ring + filled dot.
            br = 1.8 * t
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(col, max(1.0, t * 0.5)))
            p.drawEllipse(QPointF(cx, cy), br, br)
            p.setPen(QPen(QColor(Qt.GlobalColor.black), 1))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(cx, cy), t * 0.6, t * 0.6)
        else:
            # Classic: split wing bars + centre dot.
            p.drawRect(QRectF(w / 4, cy - 3, w / 6, 6))
            p.drawRect(QRectF(w - w / 4 - w / 6, cy - 3, w / 6, 6))
            p.drawEllipse(QRectF(cx - 3, cy - 3, 9, 9))

    def resizeEvent(self, event):
        self.pitchItems = []
        # Detach the SVS item from the outgoing scene BEFORE we replace
        # it. QGraphicsScene deletes its items on destruction; if the
        # item rides the old scene down, the Python wrapper is left
        # pointing at a deleted C++ object and the next attach crashes.
        # Seen on eglfs (Pi), where fullscreen startup produces extra
        # resize events with the old scene destroyed in between.
        _svs_item = getattr(self, "_svs_item", None)
        if _svs_item is not None:
            try:
                _old_scene = _svs_item.scene()
                if _old_scene is not None:
                    _old_scene.removeItem(_svs_item)
            except RuntimeError:
                # C++ side already deleted — drop the dead wrapper;
                # _attach_svs_item_if_ready rebuilds it from self.svs.
                self._svs_item = None
        if self.font_percent:
            self.fontSize = qRound(self.width() * self.font_percent)
            self.minorDivWidth = qRound(self.fontSize * 0.3)
            self.majorDivWidth = self.minorDivWidth * 4
            self.numberedDivWidth = self.minorDivWidth * 5
            self.bankMarkSize = qRound(self.fontSize * 0.3 )
        #Setup the scene that we use for the background of the AI
        sceneHeight = self.height() * 4.5
        sceneWidth = math.sqrt(self.width() * self.width() +
                               self.height() * self.height())
        self.pixelsPerDeg = self.height() / self.pitchDegreesShown
        self.scene = QGraphicsScene(0, 0, sceneWidth, sceneHeight)
        # Setup default values
        if self.bankAngleRadius is None:
            self.bankAngleRadius = self.height() / 3
        # Get a failure scene ready in case it's needed
        self.fail_scene = QGraphicsScene(0, 0, sceneWidth, sceneHeight)
        self.fail_scene.addRect(0,0, sceneWidth, sceneHeight, QPen(QColor(Qt.GlobalColor.white)), QBrush(QColor(50,50,50)))
        font = QFont(self.font_family, 80, QFont.Weight.Bold)
        t = self.fail_scene.addSimpleText("XXX", font)
        t.setPen (QPen(QColor(Qt.GlobalColor.red)))
        t.setBrush (QBrush(QColor(Qt.GlobalColor.red)))
        r = t.boundingRect()
        t.setPos ((sceneWidth-r.width())/2, (sceneHeight-r.height())/2)

        #Draw the Blue and Brown rectangles
        gradientBlue = QLinearGradient(0, 0, 0, sceneHeight / 2)
        gradientBlue.setColorAt(0.7, QColor(0, 51, 102))
        gradientBlue.setColorAt(1.0, QColor(51, 153, 255))
        gradientBlue.setSpread(QGradient.Spread.PadSpread)
        self.blue_pen = QPen(QColor(Qt.GlobalColor.blue))
        self.gblue_brush = QBrush(gradientBlue)
        gradientLGray = QLinearGradient(0, 0, 0, sceneHeight / 2)
        gradientLGray.setColorAt(0.7, QColor(100, 100, 100))
        gradientLGray.setColorAt(1.0, QColor(153, 153, 153))
        gradientLGray.setSpread(QGradient.Spread.PadSpread)
        self.gray_sky = QBrush(gradientLGray)
        if self.getAIOld() or self.getAIBad():
            brush = self.gray_sky
        else:
            brush = self.gblue_brush
        self.sky_rect = self.scene.addRect(0, 0, sceneWidth, sceneHeight / 2, self.blue_pen, brush)
        self.setScene(self.scene)
        gradientBrown = QLinearGradient(0, sceneHeight / 2, 0, sceneHeight)
        gradientBrown.setColorAt(0.0, QColor(105, 46, 1))
        gradientBrown.setColorAt(0.3, QColor(244, 164, 96))
        gradientBrown.setSpread(QGradient.Spread.PadSpread)
        self.brown_pen = QPen(QColor(160, 82, 45))  # Brown Color
        self.gbrown_brush = QBrush(gradientBrown)
        gradientDGray = QLinearGradient(0, sceneHeight / 2, 0, sceneHeight)
        gradientDGray.setColorAt(0.0, QColor(20, 20, 20))
        gradientDGray.setColorAt(0.2, QColor(75, 75, 75))
        gradientDGray.setSpread(QGradient.Spread.PadSpread)
        self.gray_land = QBrush(gradientDGray)
        if self.getAIOld() or self.getAIBad():
            brush = self.gray_land
        else:
            brush = self.gbrown_brush
        self.land_rect = self.scene.addRect(0, sceneHeight / 2 + 1, sceneWidth, sceneHeight,
                           self.brown_pen, brush)

        self.setScene(self.scene)

        #Draw the main horizontal line
        pen = QPen(QColor(Qt.GlobalColor.white))
        pen.setWidth(qRound(self.fontSize * 0.05))
        # z=1 (with the pitch ladder) so the zero-pitch reference line
        # stays visible OVER the SVS terrain (z=0.5) — otherwise
        # mountains rising above the horizon hide it, removing the
        # attitude reference exactly when terrain fills the view.
        _horizon = self.scene.addLine(
            0, sceneHeight / 2, sceneWidth, sceneHeight / 2, pen)
        _horizon.setZValue(1)
        # draw the degree hash marks
        pen.setColor(Qt.GlobalColor.white)
        w = self.scene.width()
        h = self.scene.height()
        f = QFont(self.font_family)
        f.setPixelSize(self.fontSize)

        # Draw the tick mark lines on the scene
        for i in range(-90, 91):
            if i == 0:  # Don't draw a line at zero
                pass
            elif i % self.numberedDiv == 0:
                left = w / 2 - self.numberedDivWidth / 2
                right = w / 2 + self.numberedDivWidth / 2
                y = h / 2 - self.pixelsPerDeg * i

                l = self.scene.addLine(left, y, right, y, pen)
                l.setZValue(1)
                self.pitchItems.append((i, l))
                t = self.scene.addText(str(i))
                t.setFont(f)
                self.scene.setFont(f)
                t.setDefaultTextColor(Qt.GlobalColor.white)
                t.setX(right + 5)
                t.setY(y - t.boundingRect().height() / 2)
                t.setZValue(1)
                self.pitchItems.append((i, t))

                t = self.scene.addText(str(i))
                t.setFont(f)
                self.scene.setFont(f)
                t.setDefaultTextColor(Qt.GlobalColor.white)
                t.setX(left - (t.boundingRect().width() + 5))
                t.setY(y - t.boundingRect().height() / 2)
                t.setZValue(1)
                self.pitchItems.append((i, t))

            elif i % self.majorDiv == 0:
                left = w / 2 - self.majorDivWidth / 2
                right = w / 2 + self.majorDivWidth / 2
                y = h / 2 - self.pixelsPerDeg * i
                l = self.scene.addLine(left, y, right, y, pen)
                l.setZValue(1)
                self.pitchItems.append((i, l))

            elif i % self.minorDiv == 0:
                left = w / 2 - self.minorDivWidth / 2
                right = w / 2 + self.minorDivWidth / 2
                y = h / 2 - self.pixelsPerDeg * i
                l = self.scene.addLine(left, y, right, y, pen)
                l.setZValue(1)
                self.pitchItems.append((i, l))
        self.setPitchItems()

        # Draws the static overlay stuff to a pixmap
        self.map = QPixmap(self.width(), self.height())
        self.map.fill(Qt.GlobalColor.transparent)
        p = QPainter(self.map)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # change width and height to the view instead of the scene
        w = self.width()
        h = self.height()
        r = self.bankAngleRadius
        self._draw_aircraft_symbol(p, w, h)

        m = self.bankMarkSize
        p.setBrush(QColor(Qt.GlobalColor.white))
        p.translate(w / 2, h/2 - r)
        triangle = QPolygonF([QPointF(m,  m*2),
                             QPointF(-m, m*2),
                             QPointF(0,  m/2)])
        p.drawPolygon(triangle)


        self.overlay = self.map.toImage()

        # resizeEvent builds a new self.scene; re-attach the SVS item so it
        # tracks the current scene rather than being orphaned on the old one.
        self._attach_svs_item_if_ready()

        self.redraw()

    def set_svs_config(self, config: dict):
        """Initialise the SVS renderer from a config dict (called by screenbuilder).

        SVS is added to the QGraphicsScene as a low-Z item so the pitch
        ladder and other scene items render on top of the terrain. Override
        the default with ``z_value`` in the SVS config block.

        The scene itself is built in ``resizeEvent``, so if this method runs
        before the first resize we defer the attachment — ``resizeEvent``
        re-runs ``_attach_svs_item_if_ready`` after rebuilding the scene.
        """
        # If we already had an SVS item, detach it from whatever scene held it
        # so we can swap in a fresh renderer cleanly.
        if getattr(self, "_svs_item", None) is not None:
            old_scene = self._svs_item.scene()
            if old_scene is not None:
                old_scene.removeItem(self._svs_item)
            self._svs_item = None

        self.svs = SVSRenderer(config)
        # Z-order layers inside the AI scene:
        #   z =  1.0  — pitch ladder lines, numerals  (setZValue(1) in resizeEvent)
        #   z =  0.5  — SVS terrain (this item, default)
        #   z =  0.0  — sky_rect, land_rect (the static artificial horizon)
        # So SVS covers the static blue/brown background but stays behind the
        # pitch ladder. Configurable via the `z_value` SVS config key.
        z = float(config.get("z_value", 0.5))
        # GL viewport (P5): the SVS renders directly into the view's
        # backing GL surface between begin/endNativePainting — no
        # offscreen FBO, no glReadPixels. The QPainter scene items
        # (pitch ladder, symbology) render through Qt's GL paint
        # engine on the same surface. FullViewportUpdate is required
        # for GL viewports (partial updates are not supported).
        from PyQt6.QtOpenGLWidgets import QOpenGLWidget
        if not isinstance(self.viewport(), QOpenGLWidget):
            glw = QOpenGLWidget()
            # MSAA (P7): antialiases the whole AI — terrain silhouettes
            # and QPainter symbology alike. The driver grants the
            # closest supported sample count (0 if unsupported), so
            # this degrades silently.
            # Default 2x: at panel sizes the visual difference from 4x is
            # marginal, but terrain fill cost roughly halves — measured
            # decisive for holding 30 Hz at metro worst-case poses.
            samples = int(config.get("msaa_samples", 2))
            if samples > 1:
                fmt = QSurfaceFormat()
                fmt.setSamples(samples)
                glw.setFormat(fmt)
            self.setViewport(glw)
            self.setViewportUpdateMode(
                QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        # Display frame rate (P4): the AI frame clock's tick rate.
        self.set_frame_rate(config.get("frame_rate", 30.0))
        self._svs_z = z
        self._svs_item = make_svs_item(self.svs, self)
        self._svs_item.setZValue(z)
        self._attach_svs_item_if_ready()

    def _attach_svs_item_if_ready(self):
        """Idempotently add the SVS scene item to the current scene.
        ``resizeEvent`` rebuilds ``self.scene`` on every resize, so the item
        has to be re-attached each time the scene changes. If the item's
        C++ object was deleted with a destroyed scene, rebuild the thin
        wrapper around the surviving SVSRenderer."""
        if getattr(self, "svs", None) is None:
            return
        # self.scene is the inherited QGraphicsView.scene method until
        # resizeEvent assigns the instance attribute — guard against that.
        scene = self.__dict__.get("scene")
        if scene is None:
            return
        item = getattr(self, "_svs_item", None)
        if item is not None:
            try:
                if item.scene() is scene:
                    return
                scene.addItem(item)
                return
            except RuntimeError:
                pass  # wrapper points at a deleted C++ object — rebuild
        self._svs_item = make_svs_item(self.svs, self)
        self._svs_item.setZValue(getattr(self, "_svs_z", 0.5))
        scene.addItem(self._svs_item)

    def _fpmValueChanged(self, key, value):
        setattr(self, f'_fpm_{key.lower()}', value)
        # Feed the dead-reckoning inputs; the frame clock repaints.
        if key == "GS":
            self._pose.set_dynamics(gs_kt=value)
        elif key == "TRACK":
            self._pose.set_dynamics(track_deg=value)
        elif key == "VS":
            self._pose.set_dynamics(vs_fpm=value)
        self._frame_dirty = True

    def _fpmFailChanged(self, key, fail):
        self._fpm_fail[key] = fail
        self._pose.set_fail(key, fail)
        if self.isVisible():
            self.update()

    def _fpmBadChanged(self, key, bad):
        self._fpm_bad[key] = bad
        if self.isVisible():
            self.update()

    def update(self):  # noqa: A003 — deliberate QWidget.update override
        """Route repaint requests to the viewport widget. With the P5
        QOpenGLWidget viewport, update() on the view widget itself
        does not invalidate the GL surface — only the initial expose
        would ever paint. viewport().update() is correct for both GL
        and raster viewports."""
        self.viewport().update()

    def _positionValueChanged(self, key, value):
        """GPS/baro position inputs: store raw and timestamp into the
        pose source. The frame clock samples the interpolated pose."""
        if key == "LAT":
            self._svs_lat = value
            self._pose.set_position(value, self._svs_lon)
        elif key == "LONG":
            self._svs_lon = value
            self._pose.set_position(self._svs_lat, value)
        elif key == "ALT":
            self._svs_alt = value
            self._pose.set_altitude(value)
        self._frame_dirty = True

    def set_frame_rate(self, fps):
        """(Re)start the display frame clock at *fps* (clamped 5-60)."""
        fps = max(5.0, min(60.0, float(fps)))
        self._frame_rate = fps
        self._frame_timer.start(int(round(1000.0 / fps)))

    def _frame_tick(self):
        """Display-rate tick: sample the interpolated pose, apply it,
        and repaint — but only when something actually changed, so a
        parked aircraft costs near-zero CPU."""
        if not self.isVisible() or self.__dict__.get("scene") is None:
            return
        sampled = self._pose.sample()
        if sampled is not None:
            lat, lon, alt = sampled
            self._svs_lat = lat
            self._svs_lon = lon
            if alt is not None:
                self._svs_alt = alt
        pose_key = (round(self._svs_lat, 8), round(self._svs_lon, 8),
                    round(self._svs_alt, 2), self._pitchAngle,
                    self._rollAngle, self._fpm_head, self._latAccel,
                    self._tas)
        if not self._frame_dirty and pose_key == self._frame_last_pose:
            return
        self._frame_last_pose = pose_key
        self._frame_dirty = False
        self.redraw()
        self.update()

    def _drawFPM(self, p, w, h):
        """Draw GPS flight path marker if data is valid and show_fpm is set."""
        if not self.show_fpm:
            return
        # VPATH is optional — if the data source can publish it
        # directly we use it, but missing/failed VPATH must not
        # disable the FPM (real-world GPS sources won't have it).
        required = ('VS', 'GS', 'TRACK', 'HEAD')
        if any(self._fpm_fail[k] for k in required):
            return
        fpm_bad = any(self._fpm_bad[k] for k in required)

        # Vertical flight path angle. Prefer the authoritative VPATH
        # FIX key when the source publishes it (X-Plane idx 18 slot 3
        # is the same value X-Plane's own primary-flight-display FPM
        # uses). Fall back to atan2(VS, GS), which is correct in
        # steady state but lags VPATH on transient descents.
        if not self._fpm_fail['VPATH']:
            fpa_deg = self._fpm_vpath
        else:
            gs_fpm = self._fpm_gs * 101.269  # knots → ft/min
            if gs_fpm > 10.0:
                fpa_deg = math.degrees(math.atan2(self._fpm_vs, gs_fpm))
            else:
                fpa_deg = 0.0
        # Drift angle: crab relative to heading, normalised ±180°.
        # TRACK (idx 18 slot 2 = hpath) is the TRUE ground track;
        # HEAD is magnetic. Subtract MAGVAR from HEAD so both legs of
        # the subtraction are in the true-north frame — otherwise the
        # FPM sits one local-mag-var off its real screen position
        # (same bug class as the pre-MAGVAR SVS projection).
        head_true = self._fpm_head - getattr(self, "_magvar", 0.0)
        drift_deg = ((self._fpm_track - head_true) + 180.0) % 360.0 - 180.0

        ppd = getattr(self, 'pixelsPerDeg', self.height() / self.pitchDegreesShown)
        sym_r = self.bankMarkSize * 0.65
        x_roll = drift_deg * ppd
        y_roll = -fpa_deg * ppd

        # Clamp to widget interior (in rolled frame, conservative)
        max_x = w / 2.0 - sym_r * 3.0
        max_y = h / 2.0 - sym_r * 3.0
        x_roll = max(-max_x, min(max_x, x_roll))
        y_roll = max(-max_y, min(max_y, y_roll))

        fpm_color = QColor(0, 200, 0) if not fpm_bad else QColor(255, 165, 0)
        pen = QPen(fpm_color)
        pen.setWidth(max(1, qRound(self.fontSize * 0.05)))

        p.save()
        p.resetTransform()
        p.translate(w / 2.0, h / 2.0)
        p.rotate(self._rollAngle * -1.0)   # align with pitch ladder
        p.translate(x_roll, y_roll)         # move to flight-path position
        p.rotate(self._rollAngle)           # symbol stays upright in display space
        p.setPen(pen)
        p.setBrush(Qt.GlobalColor.transparent)
        p.drawEllipse(QPointF(0.0, 0.0), sym_r, sym_r)
        p.drawLine(QPointF(-sym_r * 2.4, 0.0), QPointF(-sym_r * 1.1, 0.0))
        p.drawLine(QPointF( sym_r * 1.1, 0.0), QPointF( sym_r * 2.4, 0.0))
        p.drawLine(QPointF(0.0, -sym_r * 1.1), QPointF(0.0, -sym_r * 2.0))
        p.restore()

    # the pitchItems list contains a tuple that represents all of the tick marks
    # and text of the Pitch graducations.  The first item of the tuple is the angle
    # and the second is the item reference.  We use this to make the tick marks
    # disappear when they are a certain distance from the current pitch angle
    def setPitchItems(self):
        for each in self.pitchItems:
            if abs(each[0] - self._pitchAngle) < self.visiblePitchAngle:
                each[1].setOpacity(self.pitchOpacity)
            else:
                each[1].setOpacity(0)

    def redraw(self):
        self.resetTransform()
        self.centerOn(self.scene.width() / 2,
                      self.scene.height() / 2 +
                      self._pitchAngle * self.pixelsPerDeg * - 1.0)
        self.rotate(self._rollAngle * -1.0)

# We use the paintEvent to draw on the viewport the parts that aren't moving.
    def paintEvent(self, event):
        # Wall-clock-bound paintEvent timing for perf debugging. When
        # svs_perf_log is enabled on the SVS renderer we report the
        # full paintEvent duration AND the gap between consecutive
        # paintEvents alongside the SVS-internal timings, so we can
        # see how much of the per-frame budget is consumed inside vs
        # outside SVS. Cheap to leave compiled in — perf object is
        # held by the SVS renderer and only does work when its
        # ``enabled`` flag is set.
        import time as _time
        perf = getattr(getattr(self, "svs", None), "_perf", None)
        if perf is not None and perf.enabled:
            _pe_t0 = _time.perf_counter_ns()
            _pe_last = getattr(self, "_perf_last_paint_ns", 0)
            if _pe_last:
                perf.add_ns("frame.gap_between_paintEvent",
                            _pe_t0 - _pe_last)
            self._perf_last_paint_ns = _pe_t0
        else:
            _pe_t0 = 0

        super(AI, self).paintEvent(event)
        w = self.width()
        h = self.height()
        r = self.bankAngleRadius
        m = self.bankMarkSize
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # SVS terrain is rendered as a QGraphicsItem inside super().paintEvent()
        # above, at a low z-value (default -10). The pitch ladder (z=1) and any
        # other scene items render on top. Overlay symbology below is painted
        # directly onto the viewport, so it always lands in front of SVS.

        # Put the static overlay image on the view
        p.drawImage(self.rect(), self.overlay)

        # SVS UNAVAIL annunciation. The SVS is GL-required; if the GL
        # renderer failed to initialise or draw, it disables itself and
        # we annunciate rather than silently showing the sky/ground
        # two-tone as if terrain awareness were available.
        # NOTE: screenbuilder applies YAML options as raw attributes,
        # so self.svs can be the config DICT on widgets configured that
        # way — use getattr with defaults, never attribute access.
        _svs = getattr(self, "svs", None)
        if (getattr(_svs, "enabled", False)
                and getattr(_svs, "gl_failed", False)):
            p.save()
            _af = QFont(self.font_family, -1, QFont.Weight.Bold)
            _af.setPixelSize(max(12, qRound(self.fontSize * 0.9)))
            p.setFont(_af)
            p.setPen(QPen(QColor(255, 176, 0)))
            p.drawText(QRectF(0, h * 0.18, w, h * 0.12),
                       Qt.AlignmentFlag.AlignCenter, "SVS UNAVAIL")
            p.restore()

        pen = QPen(Qt.GlobalColor.white)
        pen.setWidth(qRound(self.fontSize * 0.025))
        p.setPen(pen)
        p.setBrush(QColor(Qt.GlobalColor.white))
        marks = QPen(Qt.GlobalColor.white)

        p.translate(w / 2, h / 2)

        # Slip / Skid ball
        p.setPen(QColor(Qt.GlobalColor.black))
        p.setBrush(QColor(Qt.GlobalColor.white))
        p.drawEllipse(QPointF(self._latAccel * -m*12, -r + m*3), m*0.8, m*0.8)

        p.rotate(self._rollAngle * -1.0)
        # Add moving Bank Angle Markers
        marks.setWidth(qRound(self.fontSize * 0.05))
        p.setPen(marks)
        p.setBrush(QColor(Qt.GlobalColor.white))
        smallMarks = [10, 20, 45]
        largeMarks = [30, 60]
        shortLine = QLineF(0, -r, 0, -(r-m))
        longLine = QLineF(0, -(r+m), 0, -(r-m))
        for angle in smallMarks:
            p.rotate(angle)
            p.drawLine(shortLine)
            p.rotate(- 2 * angle)
            p.drawLine(shortLine)
            p.rotate(angle)
        for angle in largeMarks:
            p.rotate(angle)
            p.drawLine(longLine)
            p.rotate(- 2 * angle)
            p.drawLine(longLine)
            p.rotate(angle)
        triangle = QPolygonF([QPointF(m/2, -(r+m/2)),
                             QPointF(-m/2, -(r+m/2)),
                             QPointF(0, -(r - m/2))])
        p.drawPolygon(triangle)
        # Draw standard rate turn markers
        if self.drawBankMarkers:
            a = math.degrees(math.atan(self._tas/364.0))
            if a > self.bankAngleMaximum:
                a = self.bankAngleMaximum
            diamond = QPolygonF([QPointF(0, -r),
                                QPointF(-m*0.8, -(r+m*0.8)),
                                QPointF(-0, -r - m*1.6),
                                QPointF(m*0.8, -(r+m*0.8))])
            p.setBrush(Qt.GlobalColor.transparent)
            p.rotate(a)
            p.drawPolygon(diamond)
            p.rotate(-2 * a)
            p.drawPolygon(diamond)

        self._drawFPM(p, w, h)

        if _pe_t0:
            perf.add_ns("frame.ai_paintEvent_total",
                        _time.perf_counter_ns() - _pe_t0)

    # We don't want this responding to keystrokes
    def keyPressEvent(self, event):
        pass

    # Don't want it acting with the mouse scroll wheel either
    def wheelEvent(self, event):
        pass

    def showEvent(self, event):
        self.redraw()

    def setRollAngle(self, angle):
        if angle != self._rollAngle and not self.getAIFail():
            self._rollAngle = common.bounds(-180, 180, angle)
            self._frame_dirty = True

    def getRollAngle(self):
        return self._rollAngle

    rollAngle = property(getRollAngle, setRollAngle)

    def setLateralAcceleration(self, value):
        if value != self._latAccel:
            self._latAccel = common.bounds(-0.3, 0.3, value)
            self._frame_dirty = True

    def setTrueAirspeed(self, value):
        if value != self._tas:
            self._tas = value
            self._frame_dirty = True

    def getPitchAngle(self):
        return self._pitchAngle

    def setPitchAngle(self, angle):
        if angle != self._pitchAngle and not self.getAIFail():
            self._pitchAngle = common.bounds(-90, 90, angle)
            self.setPitchItems()
            self._frame_dirty = True

    pitchAngle = property(getPitchAngle, setPitchAngle)

    def getPitchAngle(self):
        return self._pitchAngle

    def getAIFail(self):
        return True in self._AIFail.values()

    def setAIFailRoll(self, fail):
        self.setFail(fail,'ROLL')

    def setAIFailPitch(self, fail):
        self.setFail(fail,'PITCH')

    def setAIFailLAcc(self, fail):
        self.setFail(fail,'ALAT')

    def setAIFailTAS(self, fail):
        self.setFail(fail,'TAS')

    def setFail(self, fail,item=None):
        if fail != self._AIFail[item]:
            self._AIFail[item] = fail
            if hasattr(self, 'fail_scene'):
                if self.getAIFail():
                    self.resetTransform()
                    self.setScene (self.fail_scene)
                else:
                    self.setScene (self.scene)
                    # Initially set to grey
                    # we may have old data while recovering
                    if hasattr(self, 'sky_rect'):
                        if self.getAIOld() or self.getAIBad():
                            self.sky_rect.setBrush (self.gray_sky)
                            self.land_rect.setBrush (self.gray_land)
                        else:
                            self.sky_rect.setBrush (self.gblue_brush)
                            self.land_rect.setBrush (self.gbrown_brush)
                    self.redraw()

    def getAIOld(self):
        return True in self._AIOld.values()

    def setAIOldRoll(self, old):
        self.setOld(old,'ROLL')

    def setAIOldPitch(self, old):
        self.setOld(old,'PITCH')

    def setAIOldLAcc(self, old):
        self.setOld(old,'ALAT')

    def setAIOldTAS(self, old):
        self.setOld(old,'TAS')

    def setOld(self, old, item=None):
        log.debug("Set AI Old")
        if old != self._AIOld[item]:
            self._AIOld[item] = old
            if hasattr(self, 'sky_rect'):
                if self.getAIOld():
                    self.sky_rect.setBrush (self.gray_sky)
                    self.land_rect.setBrush (self.gray_land)
                    #self.old_text.show()
                else:
                    self.sky_rect.setBrush (self.gblue_brush)
                    self.land_rect.setBrush (self.gbrown_brush)
                    #self.old_text.hide()
                self.redraw()

    def getAIBad(self):
        return True in self._AIBad.values()

    def setAIBadRoll(self, bad):
        self.setBad(bad,'ROLL')

    def setAIBadPitch(self, bad):
        self.setBad(bad,'PITCH')

    def setAIBadLAcc(self, bad):
        self.setBad(bad,'ALAT')

    def setAIBadTAS(self, bad):
        self.setBad(bad,'TAS')

    def setBad(self, bad, item=None):
        log.debug("Set AI Bad")
        if bad != self._AIBad[item]:
            self._AIBad[item] = bad
            if hasattr(self, 'sky_rect'):
                if self.getAIBad():
                    self.sky_rect.setBrush (self.gray_sky)
                    self.land_rect.setBrush (self.gray_land)
                    #self.bad_text.show()
                else:
                    self.sky_rect.setBrush (self.gblue_brush)
                    self.land_rect.setBrush (self.gbrown_brush)
                    #self.bad_text.hide()
                self.redraw()




class FDTarget(QGraphicsView):
    def __init__(self, center, pixelsPerDeg, parent=None):
        super(FDTarget, self).__init__(parent)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0%); border: 0px")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.aicenter = center
        self.pixelsPerDeg = pixelsPerDeg

    def resizeEvent(self, event):
        self.w = self.width()
        self.h = self.height()
        polyheight = 8
        self.poly_points = [(-self.w/2,-polyheight/2)
                           ,( self.w/2,-polyheight/2)
                           ,( self.w/2, polyheight/2)
                           ,(-self.w/2, polyheight/2)]

        self.scene = QGraphicsScene(0, 0, self.w*2, self.w*2)
        pen = QPen(QColor(Qt.GlobalColor.black))
        brush = QBrush (QColor (Qt.GlobalColor.magenta))
        ps = [QPointF (x,y) for x,y in self.poly_points]
        fdpoly = QPolygonF (ps)
        self.poly = self.scene.addPolygon (fdpoly, pen, brush)
        self.poly.setX(self.w)
        self.poly.setY(self.w)

        self.setScene(self.scene)
        self.aicenter.setX (self.aicenter.x()-self.w/2)
        self.aicenter.setY (self.aicenter.y()-self.h/2)
        self.centerOn (self.w, self.w)

    def update(self, fdpitch, fdroll):
        self.move (qRound(self.aicenter.x()), qRound(self.aicenter.y() - fdpitch * self.pixelsPerDeg))
        roll = fdroll * math.pi / 180
        sinroll = math.sin(roll)
        cosroll = math.cos(roll)
        ps = [QPointF (cosroll*x - sinroll*y, sinroll*x + cosroll*y) for x,y in self.poly_points]
        fdpoly = QPolygonF (ps)
        self.poly.setPolygon (fdpoly)
