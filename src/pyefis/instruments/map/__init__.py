#  Moving map instrument -- Phase A skeleton (docs/moving_map_spec.md).
#  Top-down view: MapTransform owns ALL world->screen math, layers from
#  the provider registry paint in z order, ownship rides a configurable
#  screen anchor. Plain QWidget/QPainter: renders offscreen, no GL.

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

import pyavtools.fix as fix

from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.map import layers as map_layers

NM_M = 1852.0


class MapTransform:
    """World (lat/lon) -> screen (px). Local azimuthal-equidistant about
    the ownship position; rotation = track when track_up. The ONE owner
    of projection math -- layers never do their own (spec section 3)."""

    def __init__(self, lat, lon, range_nm, rot_deg, w, h, anchor_frac,
                 font_family="DejaVu Sans Condensed"):
        self.lat0, self.lon0 = lat, lon
        self.range_nm = range_nm
        self.rot = math.radians(rot_deg)
        self.w, self.h = w, h
        self.cx = w / 2.0
        self.cy = h * (1.0 - anchor_frac)   # ownship anchor (% up from bottom)
        self.font_family = font_family
        # range_nm = ownship anchor -> top edge
        self._px_per_m = max(1.0, self.cy) / max(1.0, range_nm * NM_M)
        self._coslat = math.cos(math.radians(lat))

    def nm_to_px(self, nm):
        return nm * NM_M * self._px_per_m

    def to_screen(self, lat, lon):
        de = (lon - self.lon0) * M_PER_DEG_LAT * self._coslat
        dn = (lat - self.lat0) * M_PER_DEG_LAT
        if self.rot:
            c, s = math.cos(self.rot), math.sin(self.rot)
            de, dn = de * c - dn * s, de * s + dn * c
        return QPointF(self.cx + de * self._px_per_m,
                       self.cy - dn * self._px_per_m)


class MovingMap(QWidget):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed"):
        super(MovingMap, self).__init__(parent)
        self.setStyleSheet("background: transparent; border: 0px")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.font_family = font_family
        # Options (screenbuilder setattrs; defaults per the spec):
        self.range_nm = 10.0
        self.range_ladder = "2,5,10,20,40,80,160"
        self.orientation = "track_up"          # or "north_up"
        self.ownship_position = 50             # percent up from bottom
        self.symbol_color = "yellow"
        self.layer_range_rings = True
        self.layer_terrain = True
        self.tile_path = ""                    # GLO-30/SRTM HGT tree
        self.terrain_mode = "relief"           # or "caution"
        self._layers = []
        self._layers_built = False

        self._lat = self._lon = 0.0
        self._track = 0.0
        self._alt_ft = 0.0
        self._old = {}
        for key, attr in (("LAT", "_lat"), ("LONG", "_lon"),
                          ("TRACKM", "_track"), ("ALT", "_alt_ft")):
            try:
                item = fix.db.get_item(key)
                item.valueChanged[float].connect(
                    lambda v, a=attr: (setattr(self, a, v), self.update()))
                item.oldChanged[bool].connect(
                    lambda o, k=key: (self._old.__setitem__(k, o),
                                      self.update()))
                setattr(self, attr, item.value)
                self._old[key] = item.old
            except KeyError:
                # Graceful missing-key pattern: run with what exists.
                self._old[key] = True

    # --- layer plumbing ---------------------------------------------------
    def _build_layers(self):
        from pyefis.instruments.map.layers import terrain  # noqa: F401
        self._layers = []
        for lid, cls in sorted(map_layers.LAYER_REGISTRY.items(),
                               key=lambda kv: kv[1].z):
            layer = cls()
            layer.enabled = bool(getattr(self, "layer_" + lid,
                                         cls.default_on))
            layer.configure(self)
            self._layers.append(layer)
        self._layers_built = True

    def set_layer(self, layer_id, on=None):
        """HMI hook: toggle (or set) a layer at runtime."""
        for layer in self._layers:
            if layer.id == layer_id:
                layer.on_toggle((not layer.enabled) if on is None else on)
                self.update()
                return True
        return False

    # --- HMI hooks (bound to buttons/encoder in screen YAML later) --------
    def _ladder(self):
        try:
            vals = [float(v) for v in str(self.range_ladder).split(",") if v]
            return vals or [10.0]
        except ValueError:
            return [10.0]

    def range_up(self):
        lad = self._ladder()
        self.range_nm = next((v for v in lad if v > self.range_nm), lad[-1])
        self.update()

    def range_down(self):
        lad = self._ladder()
        self.range_nm = next((v for v in reversed(lad)
                              if v < self.range_nm), lad[0])
        self.update()

    def toggle_orientation(self):
        self.orientation = ("north_up" if self.orientation == "track_up"
                            else "track_up")
        self.update()

    # --- painting ----------------------------------------------------------
    def _transform(self):
        rot = self._track if self.orientation == "track_up" else 0.0
        anchor = max(0.0, min(100.0,
                              float(self.ownship_position))) / 100.0
        return MapTransform(self._lat, self._lon, float(self.range_nm),
                            rot, self.width(), self.height(), anchor,
                            self.font_family)

    def paintEvent(self, event):
        if not self._layers_built:
            self._build_layers()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(16, 24, 32))
        x = self._transform()
        for layer in self._layers:
            if layer.enabled:
                p.save()
                layer.paint(p, x)
                p.restore()

        # Ownship: top-down aircraft arrow at the anchor, up = track
        # (track_up) or rotated to track (north_up).
        stale = self._old.get("LAT", True) or self._old.get("LONG", True)
        col = QColor(Qt.GlobalColor.gray) if stale \
            else QColor(self.symbol_color)
        if not col.isValid():
            col = QColor(Qt.GlobalColor.yellow)
        s = max(8.0, self.width() * 0.025)
        p.save()
        p.translate(x.cx, x.cy)
        if self.orientation == "north_up":
            p.rotate(self._track)
        p.setPen(QPen(QColor(Qt.GlobalColor.black), 1))
        p.setBrush(QBrush(col))
        p.drawPolygon(QPolygonF([
            QPointF(0, -s), QPointF(s * 0.6, s * 0.8),
            QPointF(0, s * 0.35), QPointF(-s * 0.6, s * 0.8)]))
        p.restore()

        # Status chip: range + orientation (+ NO POS when stale).
        f = QFont(self.font_family)
        f.setPixelSize(max(9, int(self.width() * 0.03)))
        p.setFont(f)
        p.setPen(QPen(QColor(255, 255, 255, 200)))
        mode = "TRK UP" if self.orientation == "track_up" else "NORTH UP"
        chip = "%g NM  %s" % (float(self.range_nm), mode)
        if stale:
            chip += "  NO POS"
        p.drawText(QRectF(6, 4, self.width() - 12, f.pixelSize() + 6),
                   Qt.AlignmentFlag.AlignLeft, chip)
