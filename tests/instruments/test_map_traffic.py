#  SPDX-License-Identifier: GPL-2.0-or-later
"""Moving-map traffic layer (P3b, CAP-401, billmallard/pyEfis#53).

The contract is docs/fix_dynamic_list_spec.md section 5. The bus side is the
real pyavtools ``fix`` database (the repo's ``fix`` fixture) carrying a
three-slot ``TFC`` block defined the way fix-gateway's
``config/database/traffic.yaml`` defines it, written in the writer's order
(fields, then ``TFCkTGT`` last).
"""

from unittest import mock

import pytest
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QWidget

from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import traffic as tfc
from pyefis.instruments.map.perf import MapPerfStats

OWN_LAT, OWN_LON = 34.0, -119.0

_SLOT_KEYS = (
    ("TGT", "int", -1, 268435455), ("ADDR", "int", 0, 16777215),
    ("ATYP", "int", 0, 15), ("LAT", "float", -90, 90),
    ("LON", "float", -180, 180), ("ALT", "float", -1000, 101350),
    ("GS", "float", 0, 4094), ("VS", "float", -32640, 32640),
    ("TRK", "float", 0, 359.9), ("TTYP", "int", 0, 3),
    ("EXTR", "bool", 0, 1), ("AIR", "bool", 0, 1), ("NIC", "int", 0, 15),
    ("NACP", "int", 0, 15), ("CAT", "int", 0, 39), ("CS", "str", 0, 0),
    ("ALRT", "int", 0, 15), ("EMRG", "int", 0, 15),
)


def _define_block(fix, n=3, palt=5000.0, magvar=None):
    for k in range(1, n + 1):
        for field, dtype, lo, hi in _SLOT_KEYS:
            key = "TFC%d%s" % (k, field)
            fix.db.define_item(key, key, dtype, lo, hi, "", 3000, "")
            it = fix.db.get_item(key)
            it.bad = it.fail = False
        fix.db.set_value("TFC%dTGT" % k, -1)
    for key, dtype, hi in (("TFCCOUNT", "int", n), ("TFCDROP", "int", 1000)):
        fix.db.define_item(key, key, dtype, 0, hi, "", 3000, "")
        fix.db.set_value(key, 0)
        it = fix.db.get_item(key)
        it.bad = it.fail = False
    if palt is not None:
        fix.db.define_item("PALT", "PALT", "float", -1000, 60000, "ft", 1000, "")
        fix.db.set_value("PALT", palt)
        it = fix.db.get_item("PALT")
        it.bad = it.fail = False
    if magvar is not None:
        fix.db.define_item("MAGVAR", "MAGVAR", "float", -180, 180, "deg", 0, "")
        fix.db.set_value("MAGVAR", magvar)
        it = fix.db.get_item("MAGVAR")
        it.bad = it.fail = False


def _write(fix, slot, ident, lat=OWN_LAT + 0.05, lon=OWN_LON, alt=5500.0,
           vs=0.0, trk=90.0, ttyp=1, nic=10, nacp=9, alrt=0, cs="N825V",
           bad=(), commit=True):
    """Write one report into *slot* in the writer's order: every field,
    then TGT last (spec 2.5)."""
    vals = {"ADDR": ident & 0xFFFFFF, "ATYP": ident >> 24, "LAT": lat,
            "LON": lon, "ALT": alt, "GS": 120.0, "VS": vs, "TRK": trk,
            "TTYP": ttyp, "EXTR": False, "AIR": True, "NIC": nic,
            "NACP": nacp, "CAT": 1, "CS": cs, "ALRT": alrt, "EMRG": 0}
    for field, v in vals.items():
        it = fix.db.get_item("TFC%d%s" % (slot, field))
        it.bad = field in bad
        it.value = v
    if commit:
        fix.db.set_value("TFC%dTGT" % slot, ident)


def _evict(fix, slot):
    fix.db.set_value("TFC%dTGT" % slot, -1)


class _Owner(QWidget):
    def __init__(self):
        super().__init__()
        self.perf = MapPerfStats()
        self._frame_dirty = False


def _layer(qtbot):
    owner = _Owner()
    qtbot.addWidget(owner)
    layer = tfc.TrafficLayer()
    layer.configure(owner)
    return layer, owner


def _render(layer, w=400, h=400, range_nm=10.0, rot=0.0):
    x = moving_map.MapTransform(OWN_LAT, OWN_LON, range_nm, rot, w, h, 0.5)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(16, 24, 32))
    p = QPainter(img)
    layer.paint(p, x)
    p.end()
    return img, x


def _inside(img, x, lat, lon):
    """A pixel well inside a nose-up (track 000) arrowhead, clear of its
    outline: 0.3 s above the centre, s = 2% of the width."""
    s = max(7.0, x.w * 0.02)
    return _at(img, x, lat, lon, dy=-int(round(0.3 * s)))


def _at(img, x, lat, lon, dx=0, dy=0):
    c = x.to_screen(lat, lon)
    return img.pixelColor(int(round(c.x())) + dx, int(round(c.y())) + dy)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------
def _t(**kw):
    base = dict(ident=1, lat=0.0, lon=0.0, alt_ft=5000.0, vs_fpm=0.0,
                trk_deg=90.0, ttyp=1, nic=10, nacp=9, alert=False,
                callsign="", stale=False, t_write=0.0)
    base.update(kw)
    return tfc.Target(**base)


@pytest.mark.parametrize("rel,tag", [
    (None, "--"), (0.0, "00"), (40.0, "00"), (500.0, "+05"),
    (-1200.0, "-12"), (12300.0, "+123"), (-60.0, "-01")])
def test_alt_tag(rel, tag):
    assert tfc.alt_tag(rel) == tag


def test_relative_altitude_needs_both_altitudes():
    assert tfc.relative_alt_ft(_t(alt_ft=5500.0), 5000.0) == 500.0
    assert tfc.relative_alt_ft(_t(alt_ft=None), 5000.0) is None
    assert tfc.relative_alt_ft(_t(alt_ft=5500.0), None) is None


@pytest.mark.parametrize("vs,d", [(None, 0), (0.0, 0), (499.0, 0),
                                  (500.0, 1), (-500.0, -1), (-2000.0, -1)])
def test_trend(vs, d):
    assert tfc.trend(_t(vs_fpm=vs)) == d


@pytest.mark.parametrize("nic,nacp,deg", [
    (10, 9, False), (5, 5, False), (4, 9, True), (10, 4, True), (0, 0, True)])
def test_degraded_is_nic_or_nacp_four_or_lower(nic, nacp, deg):
    assert tfc.is_degraded(_t(nic=nic, nacp=nacp)) is deg


def test_true_track_by_ttyp():
    assert tfc.true_track(_t(ttyp=1, trk_deg=90.0), None) == 90.0
    assert tfc.true_track(_t(ttyp=3, trk_deg=10.0), 5.0) == 10.0
    # TTYP 0: TRK is not valid -> non-directional (G§3.5.1.9)
    assert tfc.true_track(_t(ttyp=0, trk_deg=90.0), None) is None
    assert tfc.true_track(_t(ttyp=1, trk_deg=None), None) is None
    # magnetic heading: TRUE = MAG - VAR (VAR positive west)
    assert tfc.true_track(_t(ttyp=2, trk_deg=100.0), 12.0) == 88.0
    assert tfc.true_track(_t(ttyp=2, trk_deg=5.0), 12.0) == 353.0
    # ...and never guessed without a variation
    assert tfc.true_track(_t(ttyp=2, trk_deg=100.0), None) is None


def test_draw_order_puts_alerts_on_top_and_stale_under():
    a = _t(ident=1, alert=True)
    n = _t(ident=2)
    s = _t(ident=3, stale=True)
    assert [t.ident for t in tfc.draw_order([a, n, s])] == [3, 2, 1]


# ---------------------------------------------------------------------------
# reading the block (spec section 5)
# ---------------------------------------------------------------------------
def test_no_block_on_the_bus_leaves_the_layer_inert(fix, qtbot):
    layer, _owner = _layer(qtbot)
    assert layer._block is None
    img, x = _render(layer)
    assert img.pixelColor(200, 200) == QColor(16, 24, 32)


def test_block_size_is_discovered_not_hard_coded(fix, qtbot):
    _define_block(fix, n=5)
    layer, _owner = _layer(qtbot)
    assert layer._block.slots == [1, 2, 3, 4, 5]


def test_fields_are_read_on_the_tgt_write_only(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xAB4549, alt=5500.0)
    assert [t.alt_ft for t in layer.targets()] == [5500.0]
    # a refresh's fields, without its commit, change nothing yet
    _write(fix, 1, 0xAB4549, alt=6000.0, commit=False)
    assert [t.alt_ft for t in layer.targets()] == [5500.0]
    fix.db.set_value("TFC1TGT", 0xAB4549)        # same value: still a commit
    assert [t.alt_ft for t in layer.targets()] == [6000.0]


def test_state_is_keyed_by_identity_not_slot(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1)
    _write(fix, 2, 0xB2)
    assert sorted(t.ident for t in layer.targets()) == [0xA1, 0xB2]
    # A1 evicted from slot 1, re-acquired into slot 3: still one A1
    _evict(fix, 1)
    assert sorted(t.ident for t in layer.targets()) == [0xB2]
    _write(fix, 3, 0xA1)
    assert sorted(t.ident for t in layer.targets()) == [0xA1, 0xB2]
    # slot 1 reused for a new target through -1
    _write(fix, 1, 0xC3)
    assert sorted(t.ident for t in layer.targets()) == [0xA1, 0xB2, 0xC3]


def test_an_empty_slot_holds_no_entry(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1)
    _evict(fix, 1)
    assert layer.targets() == []


def test_fail_on_tgt_hides_the_target_and_old_marks_it_stale(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1)
    fix.db.get_item("TFC1TGT").old = True
    (t,) = layer.targets()
    assert t.stale is True
    fix.db.get_item("TFC1TGT").old = False
    assert layer.targets()[0].stale is False
    fix.db.get_item("TFC1TGT").fail = True
    assert layer.targets() == []
    fix.db.get_item("TFC1TGT").fail = False       # a Heartbeat clears it
    assert [t.ident for t in layer.targets()] == [0xA1]


def test_bad_fields_are_none_never_zero(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, bad=("ALT", "VS", "TRK"), ttyp=0)
    (t,) = layer.targets()
    assert t.alt_ft is None and t.vs_fpm is None and t.trk_deg is None


def test_a_target_with_no_valid_position_is_not_placed(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, lat=0.0, lon=0.0, bad=("LAT", "LON"))
    assert layer.targets() == []


def test_a_bus_write_marks_the_map_frame_dirty(fix, qtbot):
    _define_block(fix)
    layer, owner = _layer(qtbot)
    owner._frame_dirty = False
    _write(fix, 1, 0xA1)
    assert owner._frame_dirty is True


@pytest.mark.parametrize("flag", ["bad", "old", "fail"])
def test_palt_unusable_dashes_relative_altitude(fix, qtbot, flag):
    _define_block(fix, palt=5000.0)
    layer, _owner = _layer(qtbot)
    assert layer.palt_ft() == 5000.0
    setattr(fix.db.get_item("PALT"), flag, True)
    assert layer.palt_ft() is None


def test_no_palt_key_dashes_relative_altitude(fix, qtbot):
    _define_block(fix, palt=None)
    layer, _owner = _layer(qtbot)
    assert layer.palt_ft() is None


def test_a_block_never_seen_live_is_no_traffic_not_a_failure(fix, qtbot):
    """The default gateway database carries TFC with no receiver fitted:
    TFCCOUNT sits old (or fail) from boot. That is not TFC FAIL."""
    _define_block(fix)
    fix.db.get_item("TFCCOUNT").old = True
    layer, _owner = _layer(qtbot)
    assert layer.source_failed() is False
    fix.db.get_item("TFCCOUNT").fail = True
    assert layer.source_failed() is False
    # the receiver comes up, then fails: now it is a failure
    it = fix.db.get_item("TFCCOUNT")
    it.old = it.fail = False
    fix.db.set_value("TFCCOUNT", 1)
    it.fail = True
    assert layer.source_failed() is True


def test_source_failed_follows_tfccount(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    assert layer.source_failed() is False
    fix.db.get_item("TFCCOUNT").fail = True
    assert layer.source_failed() is True
    fix.db.get_item("TFCCOUNT").fail = False
    fix.db.get_item("TFCCOUNT").old = True        # the writer has stopped
    assert layer.source_failed() is True


# ---------------------------------------------------------------------------
# pixels
# ---------------------------------------------------------------------------
def test_normal_target_is_a_filled_white_symbol(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, lat=34.05, lon=-119.0, trk=0.0)
    img, x = _render(layer, w=1000, h=1000)
    c = _inside(img, x, 34.05, -119.0)
    assert c.red() > 230 and c.green() > 230 and c.blue() > 230


def test_alerted_target_is_yellow_and_flashes_open(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, lat=34.05, lon=-119.0, trk=0.0, alrt=1)
    img, x = _render(layer, w=1000, h=1000)
    c = _inside(img, x, 34.05, -119.0)
    assert c.red() > 230 and c.green() > 180 and c.blue() < 60
    layer._flash_on = False
    img, x = _render(layer, w=1000, h=1000)
    assert _inside(img, x, 34.05, -119.0) == QColor(16, 24, 32)


def test_degraded_target_is_open(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, lat=34.05, lon=-119.0, trk=0.0, nic=4)
    img, x = _render(layer, w=1000, h=1000)
    assert _inside(img, x, 34.05, -119.0) == QColor(16, 24, 32)


def test_stale_target_is_grey_then_hidden_past_the_cap(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, lat=34.05, lon=-119.0, trk=0.0, nic=10)
    fix.db.get_item("TFC1TGT").old = True
    img, x = _render(layer, w=1000, h=1000)
    s = max(7.0, x.w * 0.02)
    c = _inside(img, x, 34.05, -119.0)
    # open outline: the centre is background; the nose is grey ink
    assert c == QColor(16, 24, 32)
    nose = _at(img, x, 34.05, -119.0, dy=-int(s) + 2)
    assert abs(nose.red() - nose.blue()) < 25 and 90 < nose.red() < 200
    t_write = layer.targets()[0].t_write
    with mock.patch.object(tfc.time, "monotonic",
                           return_value=t_write + tfc.STALE_HIDE_S + 1.0):
        img, x = _render(layer, w=1000, h=1000)
    assert all(_at(img, x, 34.05, -119.0, dx=dx, dy=dy) == QColor(16, 24, 32)
               for dx in range(-30, 31, 5) for dy in range(-30, 31, 5))


def test_target_at_ownship_position_is_drawn(fix, qtbot):
    """No geometric ownship filter (spec 4.8, Bill's F6 ruling): a target
    sitting on ownship's own position and altitude is shown."""
    _define_block(fix, palt=5000.0)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, lat=OWN_LAT, lon=OWN_LON, alt=5000.0)
    img, x = _render(layer)
    c = _at(img, x, OWN_LAT, OWN_LON, dy=2)
    assert c.red() > 230 and c.green() > 230


def _tags(layer, rot=0.0):
    p = mock.MagicMock()
    p.fontMetrics.return_value.horizontalAdvance.return_value = 20
    p.fontMetrics.return_value.height.return_value = 12
    x = moving_map.MapTransform(OWN_LAT, OWN_LON, 10.0, rot, 400, 400, 0.5)
    layer.paint(p, x)
    return p, [c.args[-1] for c in p.drawText.call_args_list]


def test_tag_shows_relative_altitude_and_dashes_without_palt(fix, qtbot):
    _define_block(fix, palt=5000.0)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, alt=5500.0)
    _p, tags = _tags(layer)
    assert "+05" in tags
    fix.db.get_item("PALT").bad = True
    _p, tags = _tags(layer)
    assert "+05" not in tags and "--" in tags


def test_altitude_invalid_target_tag_is_dashed(fix, qtbot):
    _define_block(fix, palt=5000.0)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, bad=("ALT",))
    _p, tags = _tags(layer)
    assert set(tags) == {"--"}


def test_tfc_fail_annunciates(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _p, tags = _tags(layer)
    assert "TFC FAIL" not in tags
    fix.db.get_item("TFCCOUNT").fail = True
    _p, tags = _tags(layer)
    assert "TFC FAIL" in tags


def test_directional_symbol_rotates_with_the_map(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, trk=90.0, ttyp=1)
    p, _tags_ = _tags(layer, rot=30.0)
    # true track 90 on a map rotated 30 (track up, track 030) points 60
    # right of screen up
    assert p.rotate.call_args.args[0] == pytest.approx(60.0)
    p, _tags_ = _tags(layer, rot=0.0)
    assert p.rotate.call_args.args[0] == pytest.approx(90.0)


def test_non_directional_symbol_is_never_rotated(fix, qtbot):
    _define_block(fix)
    layer, _owner = _layer(qtbot)
    _write(fix, 1, 0xA1, ttyp=0, bad=("TRK",))
    p, _tags_ = _tags(layer, rot=30.0)
    p.rotate.assert_not_called()


# ---------------------------------------------------------------------------
# the widget
# ---------------------------------------------------------------------------
def test_layer_traffic_default_enabled_and_prop_disables(fix, qtbot):
    w = moving_map.MovingMap(None)
    qtbot.addWidget(w)
    w.resize(300, 300)
    w._build_layers()
    assert next(l for l in w._layers if l.id == "traffic").enabled is True
    w2 = moving_map.MovingMap(None)
    qtbot.addWidget(w2)
    w2.layer_traffic = False
    w2.resize(300, 300)
    w2._build_layers()
    assert next(l for l in w2._layers if l.id == "traffic").enabled is False


def test_traffic_paints_over_the_flight_plan_and_under_ownship(fix, qtbot):
    w = moving_map.MovingMap(None)
    qtbot.addWidget(w)
    w._build_layers()
    zs = {l.id: l.z for l in w._layers}
    assert zs["traffic"] > zs["flight_plan"]
