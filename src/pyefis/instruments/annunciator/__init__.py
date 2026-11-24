#  Copyright (c) 2026 Bill Mallard
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

"""The ``annunciator`` instrument (ANN1): a block of lamps, each bound to a
FIX key, that a builder places, sizes and styles like any instrument.

    [ GEAR DN ] [ PITOT HT ] [ FUEL PUMP ]
    [ ALT2 ON ] [   TRIM   ] [   GPS     ]

Each entry of the ``tiles`` option is one lamp::

    - label: GEAR DN          # the caption (default on/off text)
      key: GEARDN             # the FIX key the lamp follows (required)
      # ... and at most one of:
      when: "GEARDN eq true"  # a condition in the Button grammar
      flag: annunciate        # one of the key's own flags
      enum: {0: VLOC1, 1: VLOC2, 2: GPS, 3: GPS2}  # value -> text (NAVSRC)
      # with none of them the lamp is lit while the value is truthy
      condition_keys: [OILT]  # other keys a `when` reads
      on_text: GEAR DN        # default: label
      off_text: ""            # default: label, drawn dim
      level: status           # warning | caution | status | advisory | info | off
      flash_on_change: 5      # seconds a change is boxed and flashes; 0 = never

Rules (ANN1, makerplane BACKLOG):

- Only reported state is drawn. A lamp whose keys are old, bad or failed is
  drawn stale (grey, dashed outline, the label) -- never its last state. A
  lamp bound to the ``old``, ``bad`` or ``fail`` flag shows that flag and is
  not itself drawn stale.
- Before its keys have once been fresh, a lamp is empty, as the AFC4 strip
  is: an aircraft without the system gets no permanent caption.
- ``warning`` (red) and ``caution`` (amber) are for the key's own
  ``annunciate`` flag only, where the gateway's limit already decided (Bill,
  2026-11-22). A local condition asking for either is drawn at ``advisory``
  and logged, not refused. pyEfis adds no alert logic of its own.
- It only reads: the instrument writes no FIX key.
"""

import logging
import math
import time

from PyQt6.QtCore import QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

import pyavtools.fix as fix

from pyefis.instruments import conditions
from pyefis.instruments import tile as lamp

logger = logging.getLogger(__name__)

KIND_VALUE = "value"
KIND_WHEN = "when"
KIND_FLAG = "flag"
KIND_ENUM = "enum"

#: The flags a lamp may follow.
BINDABLE_FLAGS = conditions.FLAGS
#: Flags that ARE the source quality: such a lamp is never drawn stale.
QUALITY_FLAGS = ("old", "bad", "fail")
#: The only binding that may light red or amber (Bill, 2026-11-22). CAS
#: message bindings, the other one his ruling names, arrive with CAS3.
ALERT_FLAGS = ("annunciate",)


class TileSpec:
    """One ``tiles`` entry, parsed. ``error`` is set (and the lamp never
    drawn) when the entry cannot be used; parsing never raises."""

    def __init__(self, entry, index=0):
        self.index = index
        self.error = ""
        self.label = ""
        self.key = ""
        self.kind = KIND_VALUE
        self.when = ""
        self.flag = ""
        self.enum = {}
        self.condition_keys = []
        self.level = lamp.ADVISORY
        self.on_text = ""
        self.off_text = ""
        self.flash_s = 0.0
        self._test = None
        try:
            self._parse(entry)
        except Exception as exc:      # noqa: BLE001 -- construct-never-raises
            self.error = f"unusable tile entry: {exc}"
        if self.error:
            logger.warning("annunciator tile %d (%r): %s; not drawn",
                           index, self.label or self.key, self.error)

    def _parse(self, entry):
        if not isinstance(entry, dict):
            self.error = "not a mapping"
            return
        self.label = str(entry.get("label", "") or "")
        self.key = str(entry.get("key", "") or "").strip()
        if not self.key:
            self.error = "no key"
            return
        kinds = [k for k in (KIND_WHEN, KIND_FLAG, KIND_ENUM)
                 if entry.get(k) not in (None, "", {})]
        if len(kinds) > 1:
            self.error = f"more than one binding ({', '.join(kinds)})"
            return
        if kinds:
            self.kind = kinds[0]
        if self.kind == KIND_WHEN:
            self.when = str(entry[KIND_WHEN])
            self._test = conditions.compile_when(self.when)
        elif self.kind == KIND_FLAG:
            self.flag = str(entry[KIND_FLAG]).strip()
            if self.flag not in BINDABLE_FLAGS:
                self.error = (f"flag {self.flag!r} is not one of "
                              f"{', '.join(BINDABLE_FLAGS)}")
                return
        elif self.kind == KIND_ENUM:
            raw = entry[KIND_ENUM]
            if not isinstance(raw, dict):
                self.error = "enum must map values to text"
                return
            self.enum = {str(k).strip(): str(v) for k, v in raw.items()}
        keys = entry.get("condition_keys") or []
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",")]
        self.condition_keys = [str(k) for k in keys if str(k).strip()]
        if not self.label:
            self.label = self.key
        self.on_text = str(entry["on_text"]) if entry.get(
            "on_text") is not None else self.label
        self.off_text = str(entry["off_text"]) if entry.get(
            "off_text") is not None else self.label
        self.level = self._level(entry.get("level"))
        try:
            self.flash_s = max(0.0, float(entry.get("flash_on_change") or 0))
        except (TypeError, ValueError):
            self.flash_s = 0.0

    def _level(self, raw):
        level = str(raw or lamp.ADVISORY).strip().lower()
        if level not in lamp.LEVELS:
            logger.warning("annunciator tile %r: unknown level %r; drawn at "
                           "advisory", self.label, raw)
            return lamp.ADVISORY
        if level in lamp.ALERT_LEVELS and not (
                self.kind == KIND_FLAG and self.flag in ALERT_FLAGS):
            logger.warning(
                "annunciator tile %r: level %r needs the key's own annunciate "
                "flag (flag: annunciate); a local condition may use status, "
                "advisory, info or off. Drawn at advisory.", self.label, level)
            return lamp.ADVISORY
        return level

    @property
    def keys(self):
        """Every FIX key the lamp reads, its own first."""
        out = [self.key]
        for k in self.condition_keys:
            if k not in out:
                out.append(k)
        return out

    def enum_text(self, value):
        """The text an enum lamp shows for *value*; an unmapped value shows
        itself, so a new source value is never hidden."""
        candidates = [str(value)]
        try:
            f = float(value)
            if math.isfinite(f) and f == int(f):
                candidates.insert(0, str(int(f)))
        except (TypeError, ValueError):
            pass
        for c in candidates:
            if c in self.enum:
                return self.enum[c]
        return str(value)

    def lit(self, state, item):
        """Is the lamp on, for *state* (the conditions dict) and its own
        FIX *item*? Enum lamps are always on."""
        if self.kind == KIND_WHEN:
            return self._test(state=state) == True  # noqa: E712 -- pycond's truth
        if self.kind == KIND_FLAG:
            return bool(getattr(item, self.flag))
        if self.kind == KIND_ENUM:
            return True
        return bool(item.value)


class AnnunciatorModel:
    """What the lamps show, apart from Qt painting.

    ``items`` maps key -> FIX item (a key the database lacks is absent, and a
    lamp that needs it is never drawn). ``clock`` returns monotonic seconds;
    tests pass their own."""

    def __init__(self, specs, items, clock=time.monotonic):
        self.specs = list(specs)
        self.items = items
        self.clock = clock
        self.state = {}
        for item in items.values():
            self.state.update(conditions.item_fields(item))
        n = len(self.specs)
        self.seen_live = [False] * n
        self._last = [None] * n        # (lit, text) of the last fresh reading
        self._flash_until = [0.0] * n
        self.observe()

    def refresh(self, key, signal):
        item = self.items.get(key)
        if item is not None:
            conditions.refresh_field(self.state, item, signal)

    def _usable(self, spec):
        return not spec.error and all(k in self.items for k in spec.keys)

    def _fresh(self, spec):
        return not any(self.items[k].old or self.items[k].bad
                       or self.items[k].fail for k in spec.keys)

    def _reading(self, spec):
        item = self.items[spec.key]
        try:
            on = spec.lit(self.state, item)
        except Exception:              # noqa: BLE001 -- a bad expression is off
            logger.debug("annunciator tile %r: condition failed", spec.label,
                         exc_info=True)
            on = False
        if spec.kind == KIND_ENUM:
            return True, spec.enum_text(item.value)
        return on, (spec.on_text if on else spec.off_text)

    def observe(self):
        """Record a reading of every lamp. The first fresh reading is the
        baseline, not a change; back from stale, the reading is compared
        with the last one the pilot saw."""
        now = self.clock()
        for i, spec in enumerate(self.specs):
            if not self._usable(spec):
                continue
            if spec.kind == KIND_FLAG and spec.flag in QUALITY_FLAGS:
                fresh = self._fresh(spec) or self.seen_live[i]
            else:
                fresh = self._fresh(spec)
            if not fresh:
                self._flash_until[i] = 0.0
                continue
            self.seen_live[i] = True
            cur = self._reading(spec)
            if self._last[i] is not None and cur != self._last[i] \
                    and spec.flash_s > 0:
                self._flash_until[i] = now + spec.flash_s
            self._last[i] = cur

    def flashing(self, i, now=None):
        now = self.clock() if now is None else now
        return now < self._flash_until[i]

    def animating(self, now=None):
        now = self.clock() if now is None else now
        return any(now < t for t in self._flash_until)

    def tiles(self, now=None):
        """One :class:`tile.Tile` or ``None`` (draw nothing) per spec."""
        now = self.clock() if now is None else now
        out = []
        for i, spec in enumerate(self.specs):
            if not self._usable(spec) or not self.seen_live[i]:
                out.append(None)
                continue
            quality = spec.kind == KIND_FLAG and spec.flag in QUALITY_FLAGS
            if not quality and not self._fresh(spec):
                out.append(lamp.Tile(spec.label, spec.level, stale=True))
                continue
            on, text = self._reading(spec)
            f = self.flashing(i, now)
            out.append(lamp.Tile(text, spec.level if on else lamp.OFF,
                                 boxed=f, flash=f))
        return out


class Annunciator(QWidget):
    """The placed instrument. Options arrive by ``apply_options`` after
    construction; ``tiles`` goes through :meth:`setTiles`."""

    _fix_changed = pyqtSignal(str, str)

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None, tiles=None, clock=time.monotonic):
        super().__init__(parent)
        self.font_family = font_family
        self.font_percent = font_percent
        self.clock = clock
        # Panel options (InstrumentSpec Props in screenbuilder_factory).
        self.rows = 1
        self.cols = 0
        self.gap_px = 4
        self.corner_radius = 4
        self.border_width = 2
        self.bg_color = "#000000"
        self.bg_opacity = 75
        self.warning_color = lamp.DEFAULT_COLORS[lamp.WARNING]
        self.caution_color = lamp.DEFAULT_COLORS[lamp.CAUTION]
        self.status_color = lamp.DEFAULT_COLORS[lamp.STATUS]
        self.advisory_color = lamp.DEFAULT_COLORS[lamp.ADVISORY]
        self.info_color = lamp.DEFAULT_COLORS[lamp.INFO]
        self.off_color = lamp.DEFAULT_COLORS[lamp.OFF]

        self._tiles_cfg = None
        self._connected = set()
        self.model = AnnunciatorModel([], {}, clock=clock)
        # FIX callbacks can arrive off the GUI thread: the signal hop queues
        # them onto this widget's thread before any Qt call.
        self._fix_changed.connect(self._on_fix)
        self._timer = QTimer(self)
        self._timer.setInterval(int(lamp.BLINK_HALF_S * 1000 / 2))
        self._timer.timeout.connect(self._tick)
        self.setTiles(tiles or [])

    # -- configuration ------------------------------------------------------
    def setTiles(self, tiles):
        if isinstance(tiles, dict):
            tiles = [tiles]
        if not isinstance(tiles, (list, tuple)):
            logger.warning("annunciator: tiles must be a list, got %r; no lamps",
                           type(tiles).__name__)
            tiles = []
        if tiles == self._tiles_cfg:
            return
        self._tiles_cfg = list(tiles)
        specs = [TileSpec(e, i) for i, e in enumerate(tiles)]
        items = {}
        for spec in specs:
            if spec.error:
                continue
            for key in spec.keys:
                if key in items:
                    continue
                try:
                    items[key] = fix.db.get_item(key)
                except Exception:          # noqa: BLE001 -- graceful FIX-key init
                    logger.warning("annunciator: FIX key %s not in the "
                                   "database; its lamp is not drawn", key)
        for key, item in items.items():
            if key not in self._connected:
                conditions.connect_item(item, self._fix_changed.emit)
                self._connected.add(key)
        self.model = AnnunciatorModel(specs, items, clock=self.clock)
        self._sync_timer()
        self.update()

    def getTiles(self):
        return list(self._tiles_cfg or [])

    tiles = property(getTiles, setTiles)

    def _on_fix(self, key, signal):
        self.model.refresh(key, signal)
        self.model.observe()
        self._sync_timer()
        self.update()

    def _sync_timer(self):
        if self.model.animating():
            if not self._timer.isActive():
                self._timer.start()
        elif self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        self._sync_timer()
        self.update()

    # -- layout -------------------------------------------------------------
    def grid(self):
        """(rows, cols) the tiles are laid out in. ``cols`` 0 = as many as
        the tiles need on ``rows`` rows."""
        n = max(1, len(self.model.specs))
        try:
            rows = max(1, int(self.rows))
        except (TypeError, ValueError):
            rows = 1
        try:
            cols = int(self.cols)
        except (TypeError, ValueError):
            cols = 0
        if cols <= 0:
            cols = math.ceil(n / rows)
        return rows, max(1, cols)

    def tile_rects(self):
        """One QRectF per spec, row-major; a spec past the grid gets None."""
        rows, cols = self.grid()
        gap = max(0.0, float(self.gap_px))
        w = (self.width() - gap * (cols + 1)) / cols
        h = (self.height() - gap * (rows + 1)) / rows
        out = []
        for i in range(len(self.model.specs)):
            r, c = divmod(i, cols)
            if r >= rows or w <= 0 or h <= 0:
                out.append(None)
                continue
            out.append(QRectF(gap + c * (w + gap), gap + r * (h + gap), w, h))
        return out

    def colors(self):
        return {lamp.WARNING: self.warning_color,
                lamp.CAUTION: self.caution_color,
                lamp.STATUS: self.status_color,
                lamp.ADVISORY: self.advisory_color,
                lamp.INFO: self.info_color,
                lamp.OFF: self.off_color}

    def _templates(self):
        out = []
        for spec in self.model.specs:
            if spec.error:
                continue
            out += [spec.label, spec.on_text, spec.off_text]
            out += list(spec.enum.values())
        return [t for t in out if t] or [" "]

    # -- paint --------------------------------------------------------------
    def paintEvent(self, event):
        tiles = self.model.tiles()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            if not any(t is not None for t in tiles):
                return
            try:
                alpha = max(0.0, min(1.0, float(self.bg_opacity) / 100.0))
            except (TypeError, ValueError):
                alpha = 0.75
            if alpha > 0:
                bg = QColor(self.bg_color)
                bg.setAlphaF(alpha)
                p.fillRect(self.rect(), bg)
            rects = self.tile_rects()
            sized = [r for r in rects if r is not None]
            if not sized:
                return
            border = max(1.0, float(self.border_width))
            pad = border * 2 + min(sized[0].height(), sized[0].width()) * 0.06
            scale = self.font_percent if self.font_percent else 1.0
            px = lamp.fit_px(p.device(), self.font_family, self._templates(),
                             sized[0].width() - 2 * pad,
                             sized[0].height() - 2 * pad,
                             sized[0].height() * 0.5 * scale)
            now = self.clock()
            colors = self.colors()
            for t, r in zip(tiles, rects):
                if t is None or r is None:
                    continue
                lamp.paint_tile(p, r, t, colors, family=self.font_family,
                                px=px, border_px=border,
                                radius=float(self.corner_radius or 0), now=now)
        finally:
            p.end()
