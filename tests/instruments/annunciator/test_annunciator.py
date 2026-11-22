#  SPDX-License-Identifier: GPL-2.0-or-later
"""The ``annunciator`` instrument (ANN1) and the shared lamp tile.

Requirement IDs are in ``docs/annunciator_widget_spec.md`` section 4; every
test docstring names the IDs it verifies.
"""

import logging
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.instruments import annunciator as ann
from pyefis.instruments import conditions
from pyefis.instruments import tile as lamp
from pyefis.screens import screenbuilder_factory as factory
from pyefis.screens import screenbuilder_options

# key, dtype, min, max, tol -- shapes like fix-gateway's database
KEYS = [
    ("GEARDN", "bool", None, None, 2000),
    ("PITOTHT", "bool", None, None, 2000),
    ("OILP", "float", 0.0, 200.0, 2000),
    ("OILT", "float", 0.0, 300.0, 2000),
    ("NAVSRC", "int", 0, 3, 0),
]
INITIAL = {"int": 0, "float": 0.0, "bool": False}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def db(fix):
    """The test keys, defined but NOT yet fresh (pyavtools starts every
    item bad and failed); ``set(key, value, old, bad, fail, annunciate)``
    writes one and returns the item."""
    for key, dtype, lo, hi, tol in KEYS:
        fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
        fix.db.get_item(key).value = INITIAL[dtype]

    def set_(key, value=None, old=False, bad=False, fail=False,
             annunciate=False):
        item = fix.db.get_item(key)
        if value is not None:
            item.value = value
        item.old, item.bad, item.fail = old, bad, fail
        item.annunciate = annunciate
        return item

    fix.db.clientthread.sendqueue.put.reset_mock()
    set_.fix = fix
    return set_


def model(entries, db, clock=None):
    specs = [ann.TileSpec(e, i) for i, e in enumerate(entries)]
    items = {}
    for s in specs:
        if s.error:
            continue
        for k in s.keys:
            try:
                items[k] = db.fix.db.get_item(k)
            except KeyError:
                pass
    m = ann.AnnunciatorModel(specs, items, clock=clock or Clock())
    for item in items.values():
        conditions.connect_item(
            item, lambda key, signal: (m.refresh(key, signal), m.observe()))
    return m


def only(m, now=None):
    tiles = m.tiles(now)
    assert len(tiles) == 1
    return tiles[0]


# -- bindings ---------------------------------------------------------------

def test_condition_in_the_button_grammar(db):
    """ANN-BIND-001: a ``when`` string in the Button grammar lights the tile,
    reading other keys through condition_keys."""
    db("OILP", 60.0)
    db("OILT", 100.0)
    m = model([{"label": "OIL", "key": "OILP",
                "when": "OILP lt 25 or OILT gt 240",
                "condition_keys": ["OILT"], "level": "info"}], db)
    t = only(m)
    assert (t.text, t.level) == ("OIL", lamp.OFF)
    db("OILP", 20.0)
    assert only(m).level == lamp.INFO
    db("OILP", 60.0)
    db("OILT", 250.0)
    assert only(m).level == lamp.INFO


def test_condition_reads_flags_and_aux_names(db):
    """ANN-BIND-001: the state dict is the Button's: ``K.annunciate`` and the
    other flag names evaluate."""
    db("OILP", 60.0)
    m = model([{"label": "OILP ANN", "key": "OILP",
                "when": "OILP.annunciate", "level": "status"}], db)
    assert only(m).level == lamp.OFF
    db("OILP", 60.0, annunciate=True)
    assert only(m).level == lamp.STATUS


def test_flag_binding(db):
    """ANN-BIND-002: ``flag: annunciate`` follows the key's own flag."""
    db("OILP", 10.0)
    m = model([{"label": "OIL PRESS", "key": "OILP", "flag": "annunciate",
                "level": "warning"}], db)
    assert only(m).level == lamp.OFF
    db("OILP", 10.0, annunciate=True)
    t = only(m)
    assert (t.text, t.level, t.stale) == ("OIL PRESS", lamp.WARNING, False)


def test_enum_binding_shows_the_mapped_text(db):
    """ANN-BIND-003: an enum map turns the value into text; YAML may key the
    map by int or by string; an unmapped value shows itself."""
    db("NAVSRC", 2)      # NAVSRC: 0 NAV1, 1 NAV2, 2 GPS (hsi/__init__.py)
    m = model([{"label": "NAV", "key": "NAVSRC", "level": "info",
                "enum": {0: "VLOC1", "1": "VLOC2", 2: "GPS"}}], db)
    assert (only(m).text, only(m).level) == ("GPS", lamp.INFO)
    db("NAVSRC", 0)
    assert only(m).text == "VLOC1"
    db("NAVSRC", 1)
    assert only(m).text == "VLOC2"
    db("NAVSRC", 3)
    assert only(m).text == "3"


def test_enum_matches_a_whole_float_value(db):
    """ANN-BIND-003: a float key carrying a whole value (1.0) finds the map
    entry written as 1."""
    db("OILT", 1.0)
    m = model([{"label": "MODE", "key": "OILT", "enum": {1: "ONE"}}], db)
    assert only(m).text == "ONE"
    db("OILT", 1.5)
    assert only(m).text == "1.5"


def test_bare_key_is_lit_while_truthy(db):
    """ANN-BIND-004: with no when/flag/enum the tile is lit while the value is
    truthy; on/off text default to the label."""
    db("GEARDN", False)
    m = model([{"label": "GEAR DN", "key": "GEARDN", "level": "status"}], db)
    assert (only(m).text, only(m).level) == ("GEAR DN", lamp.OFF)
    db("GEARDN", True)
    assert (only(m).text, only(m).level) == ("GEAR DN", lamp.STATUS)


def test_on_and_off_text(db):
    """ANN-BIND-004: on_text / off_text replace the label per state; an empty
    off_text is an empty box."""
    db("PITOTHT", False)
    m = model([{"label": "PITOT", "key": "PITOTHT", "on_text": "PITOT HT",
                "off_text": "", "level": "advisory"}], db)
    assert (only(m).text, only(m).level) == ("", lamp.OFF)
    db("PITOTHT", True)
    assert only(m).text == "PITOT HT"


@pytest.mark.parametrize("entry", [
    {"label": "X"},                                     # no key
    {"key": "GEARDN", "when": "GEARDN eq true", "flag": "old"},  # two kinds
    {"key": "GEARDN", "flag": "highAlarm"},             # not a flag
    {"key": "GEARDN", "enum": ["GPS"]},                 # not a mapping
    {"key": "GEARDN", "when": "GEARDN is true"},         # unknown operator
    "GEARDN",                                           # not a mapping
])
def test_unusable_entry_is_not_drawn_and_never_raises(db, entry, caplog):
    """ANN-BIND-005: an entry that cannot be used logs and draws nothing; the
    instrument still builds."""
    db("GEARDN", True)
    with caplog.at_level(logging.WARNING):
        m = model([entry], db)
    assert only(m) is None
    assert "not drawn" in caplog.text


def test_missing_key_builds_and_draws_nothing(db, qtbot):
    """ANN-EMPTY-001: a key the database lacks draws nothing; construction
    never raises."""
    w = ann.Annunciator(tiles=[{"label": "NOPE", "key": "NOSUCHKEY"},
                               {"label": "GEAR", "key": "GEARDN"}])
    qtbot.addWidget(w)
    db("GEARDN", True)
    assert w.model.tiles()[0] is None
    assert w.model.tiles()[1].level == lamp.ADVISORY


# -- levels (Bill's ruling, 2026-11-22) -------------------------------------

@pytest.mark.parametrize("level", ["warning", "caution"])
@pytest.mark.parametrize("binding", [
    {"when": "OILP lt 25"},
    {},
    {"enum": {0: "LOW"}},
    {"flag": "old"},
    {"flag": "fail"},
])
def test_red_and_amber_only_from_the_annunciate_flag(db, caplog, level,
                                                     binding):
    """ANN-LVL-001: a local condition (or any binding but the key's own
    annunciate flag) asking for warning/caution is drawn at advisory and
    logged, not refused."""
    db("OILP", 0.0)
    entry = {"label": "OIL", "key": "OILP", "level": level, **binding}
    with caplog.at_level(logging.WARNING):
        spec = ann.TileSpec(entry)
    assert not spec.error
    assert spec.level == lamp.ADVISORY
    assert "annunciate" in caplog.text
    m = model([entry], db)
    flag = binding.get("flag")
    db("OILP", 10.0, old=flag == "old", fail=flag == "fail", annunciate=True)
    assert only(m).level == lamp.ADVISORY      # lit, but never red/amber


@pytest.mark.parametrize("level", ["warning", "caution"])
def test_annunciate_flag_may_use_red_and_amber(db, level):
    """ANN-LVL-001: the key's own annunciate flag keeps warning/caution."""
    assert ann.TileSpec({"key": "OILP", "flag": "annunciate",
                         "level": level}).level == level


@pytest.mark.parametrize("level", ["status", "advisory", "info", "off"])
def test_status_levels_from_any_condition(level):
    """ANN-LVL-001: the status levels are open to a local condition."""
    assert ann.TileSpec({"key": "OILP", "when": "OILP lt 25",
                         "level": level}).level == level


def test_unknown_level_is_advisory(caplog):
    """ANN-LVL-001: an unknown level is drawn at advisory and logged."""
    with caplog.at_level(logging.WARNING):
        spec = ann.TileSpec({"key": "OILP", "level": "purple"})
    assert spec.level == lamp.ADVISORY
    assert "unknown level" in caplog.text


# -- stale data and first data ----------------------------------------------

def test_empty_before_first_fresh_reading(db):
    """ANN-EMPTY-001: a key that has never been fresh draws nothing, not
    'off' -- an aircraft without the system gets no caption."""
    m = model([{"label": "GEAR DN", "key": "GEARDN"}], db)
    assert only(m) is None              # pyavtools: bad + fail at start
    db("GEARDN", False, old=True)
    assert only(m) is None
    db("GEARDN", False)
    assert only(m).level == lamp.OFF


def test_empty_until_every_condition_key_is_fresh(db):
    """ANN-EMPTY-001: a tile reading two keys waits for both."""
    db("OILP", 60.0)
    m = model([{"label": "OIL", "key": "OILP", "when": "OILT gt 240",
                "condition_keys": ["OILT"]}], db)
    assert only(m) is None
    db("OILT", 100.0)
    assert only(m).level == lamp.OFF


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
@pytest.mark.parametrize("which", ["OILP", "OILT"])
def test_stale_key_is_never_drawn_as_its_last_state(db, flag, which):
    """ANN-STALE-001: when a bound key (own or condition key) goes old, bad or
    failed, the tile shows the stale look with its label -- not its last
    state -- and returns to the reading on recovery."""
    db("OILP", 10.0)
    db("OILT", 100.0)
    m = model([{"label": "OIL", "key": "OILP", "when": "OILP lt 25",
                "condition_keys": ["OILT"], "on_text": "OIL LOW",
                "level": "status"}], db)
    assert (only(m).text, only(m).level) == ("OIL LOW", lamp.STATUS)
    db(which, None, **{flag: True})
    t = only(m)
    assert t.stale and t.text == "OIL"
    db(which, None)
    t = only(m)
    assert not t.stale and t.text == "OIL LOW"


def test_stale_overrides_an_alert(db):
    """ANN-STALE-001: an annunciate flag on stale data is not current."""
    db("OILP", 10.0, annunciate=True)
    m = model([{"label": "OIL", "key": "OILP", "flag": "annunciate",
                "level": "warning"}], db)
    assert only(m).level == lamp.WARNING
    db("OILP", None, old=True, annunciate=True)
    assert only(m).stale


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_quality_flag_tile_shows_the_flag_itself(db, flag):
    """ANN-STALE-002: a tile bound to old/bad/fail shows that flag; it is not
    drawn stale by the flag it reports."""
    db("OILP", 60.0)
    m = model([{"label": f"OILP {flag.upper()}", "key": "OILP",
                "flag": flag, "level": "advisory"}], db)
    assert only(m).level == lamp.OFF
    db("OILP", None, **{flag: True})
    t = only(m)
    assert (t.level, t.stale) == (lamp.ADVISORY, False)


# -- flash on change --------------------------------------------------------

def test_change_flashes_for_flash_on_change_seconds(db):
    """ANN-FLASH-001: a change of the shown state is boxed and flashes for
    flash_on_change seconds; the first reading is a baseline."""
    clock = Clock()
    db("GEARDN", False)
    m = model([{"label": "GEAR DN", "key": "GEARDN", "level": "status",
                "flash_on_change": 5}], db, clock)
    assert not only(m).flash                  # baseline
    db("GEARDN", True)
    t = only(m)
    assert t.flash and t.boxed and m.animating()
    clock.t += 4.9
    assert only(m).flash
    clock.t += 0.2
    assert not only(m).flash and not m.animating()


def test_no_flash_by_default(db):
    """ANN-FLASH-001: flash_on_change 0 (the default) never flashes."""
    db("GEARDN", False)
    m = model([{"label": "GEAR DN", "key": "GEARDN"}], db)
    db("GEARDN", True)
    assert not only(m).flash and not m.animating()


def test_back_from_stale_flashes_only_a_changed_reading(db):
    """ANN-FLASH-001: back from stale, the reading is compared with the last
    one shown; unchanged does not flash, changed does."""
    clock = Clock()
    db("GEARDN", True)
    m = model([{"label": "GEAR DN", "key": "GEARDN", "flash_on_change": 5}],
              db, clock)
    db("GEARDN", None, old=True)
    db("GEARDN", True)
    assert not only(m).flash
    db("GEARDN", None, old=True)
    db("GEARDN", False)
    assert only(m).flash


def test_enum_text_change_flashes(db):
    """ANN-FLASH-001: an enum tile flashes when its text changes."""
    db("NAVSRC", 0)
    m = model([{"label": "NAV", "key": "NAVSRC", "enum": {0: "VLOC1", 1: "VLOC2", 2: "GPS"},
                "flash_on_change": 3}], db)
    db("NAVSRC", 1)
    assert only(m).flash


# -- the shared tile renderer -----------------------------------------------

def _paint(tile_, w=120, h=40, now=0.0, **kw):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    lamp.paint_tile(p, QRectF(0, 0, w, h), tile_, px=14, border_px=2,
                    now=now, **kw)
    p.end()
    return img


def _colors(img):
    return {QColor(img.pixel(x, y)).name()
            for x in range(img.width()) for y in range(img.height())}


def test_none_tile_paints_nothing():
    """ANN-TILE-001: a ``None`` tile (nothing seen) paints no pixel."""
    assert _colors(_paint(None)) == {"#000000"}


@pytest.mark.parametrize("level", lamp.LEVELS)
def test_each_level_paints_its_colour(level):
    """ANN-TILE-002: each level is drawn in its colour."""
    img = _paint(lamp.Tile("AB", level))
    assert lamp.DEFAULT_COLORS[level] in _colors(img)


@pytest.mark.parametrize("level", lamp.ALERT_LEVELS)
def test_alert_levels_are_reverse_video(level):
    """ANN-TILE-002: warning and caution fill the box in the level colour."""
    img = _paint(lamp.Tile("", level))
    assert QColor(img.pixel(60, 20)).name() == lamp.DEFAULT_COLORS[level]


@pytest.mark.parametrize("level", (lamp.STATUS, lamp.ADVISORY, lamp.INFO))
def test_status_levels_are_not_filled(level):
    """ANN-TILE-002: status levels draw caption and outline, no fill."""
    img = _paint(lamp.Tile("", level))
    assert QColor(img.pixel(60, 20)).name() == "#000000"
    assert QColor(img.pixel(60, 1)).name() == lamp.DEFAULT_COLORS[level]


@pytest.mark.parametrize("level", lamp.LEVELS)
def test_stale_tile_is_grey_and_dashed_whatever_its_level(level):
    """ANN-TILE-003 / ANN-STALE-001: a stale tile paints only the degraded grey,
    with a dashed outline (gaps along the top edge), never its level colour."""
    img = _paint(lamp.Tile("OIL", level, stale=True))
    cols = _colors(img) - {"#000000"}
    assert lamp.DEFAULT_COLORS[level] not in cols
    assert all(abs(QColor(c).red() - QColor(c).green()) < 4
               and abs(QColor(c).green() - QColor(c).blue()) < 4
               for c in cols)                 # greys only (antialiasing)
    top = [QColor(img.pixel(x, 1)).name() for x in range(10, 110)]
    assert "#000000" in top and lamp.STALE_COLOR in top


def test_flash_hides_caption_and_fill_on_the_off_phase():
    """ANN-TILE-004: a flashing tile keeps its outline and drops caption and
    fill on the off phase of the shared blink."""
    on = _paint(lamp.Tile("AB", lamp.CAUTION, flash=True), now=0.0)
    off = _paint(lamp.Tile("AB", lamp.CAUTION, flash=True), now=0.6)
    assert QColor(on.pixel(60, 20)).name() != "#000000"
    assert QColor(off.pixel(60, 20)).name() == "#000000"
    assert QColor(off.pixel(60, 1)).name() == lamp.DEFAULT_COLORS[lamp.CAUTION]


def test_custom_colours_override_the_defaults():
    """ANN-TILE-002: a caller's palette wins over the defaults."""
    img = _paint(lamp.Tile("", lamp.STATUS), colors={lamp.STATUS: "#123456"})
    assert QColor(img.pixel(60, 1)).name() == "#123456"


# -- the placed instrument --------------------------------------------------

YAML_TILES = [
    {"label": "GEAR DN", "key": "GEARDN", "level": "status"},
    {"label": "PITOT HT", "key": "PITOTHT", "level": "advisory"},
    {"label": "OIL", "key": "OILP", "flag": "annunciate", "level": "warning"},
    {"label": "OIL LOW", "key": "OILP", "when": "OILP lt 25",
     "level": "warning"},
    {"label": "NAV", "key": "NAVSRC", "level": "info",
     "enum": {0: "VLOC1", 1: "VLOC2", 2: "GPS"}},
    {"label": "OILT", "key": "OILT", "level": "status"},
]


def _build(db, qtbot, options, size=(300, 100)):
    config = {"type": "annunciator", "options": options}
    w = factory.create_instrument(None, config,
                                  font_family="DejaVu Sans Condensed")
    qtbot.addWidget(w)
    screen = SimpleNamespace(instruments={0: w}, encoder_list=[])
    screenbuilder_options.apply_options(screen, 0, config)
    w.resize(*size)
    return w


def test_builds_through_apply_options_with_the_yaml_shape(db, qtbot):
    """ANN-CFG-001: the YAML options reach the widget through the real build
    path (create_instrument + apply_options)."""
    w = _build(db, qtbot, {"tiles": YAML_TILES, "rows": 2, "cols": 3,
                           "bg_opacity": 50, "corner_radius": 0,
                           "status_color": "#00ee00"})
    assert isinstance(w, ann.Annunciator)
    assert len(w.model.specs) == 6
    assert (w.rows, w.cols, w.bg_opacity, w.corner_radius) == (2, 3, 50, 0)
    assert w.colors()[lamp.STATUS] == "#00ee00"
    assert w.model.specs[3].level == lamp.ADVISORY     # Bill's ruling


def test_grid_lays_tiles_row_major(db, qtbot):
    """ANN-LAYOUT-001: rows x cols, row-major, equal cells; cols 0 = as many
    as the tiles need; a tile past the grid is not placed."""
    w = _build(db, qtbot, {"tiles": YAML_TILES, "rows": 2, "cols": 3,
                           "gap_px": 0}, size=(300, 100))
    rects = w.tile_rects()
    assert [(r.x(), r.y(), r.width(), r.height()) for r in rects[:4]] == [
        (0, 0, 100, 50), (100, 0, 100, 50), (200, 0, 100, 50),
        (0, 50, 100, 50)]
    w.rows, w.cols = 1, 0
    assert w.grid() == (1, 6)
    w.rows, w.cols = 1, 4
    assert w.tile_rects()[4] is None


def test_fix_changes_repaint_through_the_widget(db, qtbot):
    """ANN-BIND-001 / ANN-STALE-001: a FIX change reaches the painted tiles."""
    w = _build(db, qtbot, {"tiles": YAML_TILES[:1], "gap_px": 0},
               size=(120, 40))
    w.show()
    qtbot.waitExposed(w)
    status = lamp.DEFAULT_COLORS[lamp.STATUS]
    assert status not in _colors(w.grab().toImage())    # empty
    db("GEARDN", True)
    img = w.grab().toImage()
    assert QColor(img.pixel(60, 1)).name() == lamp.DEFAULT_COLORS[lamp.STATUS]
    db("GEARDN", None, old=True)
    img = w.grab().toImage()
    assert lamp.DEFAULT_COLORS[lamp.STATUS] not in _colors(img)


def test_empty_block_paints_no_background(db, qtbot):
    """ANN-EMPTY-001: with nothing seen the block paints nothing at all, not
    even its fill."""
    w = _build(db, qtbot, {"tiles": YAML_TILES, "bg_opacity": 100,
                           "bg_color": "#334455"})
    w.show()
    qtbot.waitExposed(w)
    assert "#334455" not in _colors(w.grab().toImage())


def test_writes_no_fix_key(db, qtbot):
    """ANN-RO-001: building, receiving every kind of change and painting
    queues no write to fix-gateway."""
    w = _build(db, qtbot, {"tiles": YAML_TILES, "rows": 2})
    w.show()
    qtbot.waitExposed(w)
    for key, value in (("GEARDN", True), ("PITOTHT", True), ("OILP", 10.0),
                       ("OILT", 250.0), ("NAVSRC", 1)):
        db(key, value, annunciate=True)
        w.grab()
        db(key, value, old=True)
        w.grab()
    db.fix.db.clientthread.sendqueue.put.assert_not_called()


def test_flash_timer_runs_only_while_flashing(db, qtbot):
    """ANN-FLASH-001: the repaint timer runs while a tile flashes and stops
    after."""
    clock = Clock()
    db("GEARDN", False)
    w = ann.Annunciator(clock=clock, tiles=[
        {"label": "GEAR DN", "key": "GEARDN", "flash_on_change": 2}])
    qtbot.addWidget(w)
    assert not w._timer.isActive()
    db("GEARDN", True)
    assert w._timer.isActive()
    clock.t += 2.5
    w._tick()
    assert not w._timer.isActive()


def test_tiles_set_again_with_the_same_list_keeps_state(db, qtbot):
    """ANN-CFG-001: apply_options re-delivers ``tiles`` after construction;
    the same list does not rebuild (or re-baseline) the model."""
    db("GEARDN", True)
    w = ann.Annunciator(tiles=YAML_TILES[:1])
    qtbot.addWidget(w)
    before = w.model
    w.setTiles(list(YAML_TILES[:1]))
    assert w.model is before


# -- the Button still evaluates through the shared module -------------------

def test_button_conditions_use_the_shared_evaluator(monkeypatch):
    """BTN-SHARED-001: the Button's string conditions go through
    conditions.evaluate (ORG-018: one evaluator), so breaking the shared
    evaluator changes the Button."""
    from pyefis.instruments import button
    calls = []
    monkeypatch.setattr(button.conditions, "evaluate",
                        lambda when, state: calls.append(when) or False)
    b = SimpleNamespace(
        _db_data={}, _conditions=[{"when": "X eq 1", "actions": []}],
        _dbkey=SimpleNamespace(value=False, key="K"),
        parent=SimpleNamespace(screenName="S", parent=SimpleNamespace(
            getRunningScreen=lambda: "S")))
    button.Button.processConditions(b)
    assert calls == ["X eq 1"]


# -- the editor schema's tile catalogue -------------------------------------

def test_schema_tile_catalogue_matches_the_instrument():
    """ANN-CFG-002: the schema's tile catalogue (for the configurator, ANN2)
    lists exactly the levels, flags, binding kinds and level rule the
    instrument applies."""
    from pyefis.editor import schema as eschema
    cat = eschema.build_schema()["annunciator"]
    fields = {f["name"]: f for f in cat["tile_fields"]}
    assert cat["levels"] == list(lamp.LEVELS)
    assert cat["alert_levels"] == list(lamp.ALERT_LEVELS)
    assert fields["level"]["enum"] == list(lamp.LEVELS)
    assert sorted(fields["flag"]["enum"]) == sorted(ann.BINDABLE_FLAGS)
    assert {n for n, f in fields.items() if f.get("binding")} == {
        ann.KIND_WHEN, ann.KIND_FLAG, ann.KIND_ENUM}
    assert cat["alert_bindings"] == [
        {"field": ann.KIND_FLAG, "value": v} for v in ann.ALERT_FLAGS]
    assert cat["alert_fallback_level"] == lamp.ADVISORY
    # every field the parser reads is listed, and nothing else
    assert set(fields) == {"label", "key", "when", "flag", "enum",
                           "condition_keys", "on_text", "off_text", "level",
                           "flash_on_change"}
    spec = ann.TileSpec({f: None for f in fields} | {"key": "OILP"})
    assert not spec.error
