#  SPDX-License-Identifier: GPL-2.0-or-later
"""The CAS tones (CAS4, docs/cas_widget_spec.md, CASW-AUR-*).

Each test names the requirement it verifies. The scheduler is driven chunk by
chunk on the audio clock; the ALSA sink is driven through the real libasound
into a ``file`` PCM, so the R9 ordering is checked on the bytes that reached
the device, not on the scheduler's word for it.
"""

import logging
import os

import pytest

from pyefis.instruments.cas import alsa
from pyefis.instruments.cas import aural
from pyefis.instruments.cas import model as cm
from pyefis.instruments.cas import tones as tn
from tests.instruments.autopilot.conftest import AFC1_KEYS, INITIAL

from .test_model import Bus, Clock, make

D, W, C = tn.DISCONNECT, tn.WARNING, tn.CAUTION
TONE = {t.id: t for t in tn.TONES}
CHUNK_S = tn.CHUNK_FRAMES / float(tn.RATE)


def run(s, active, seconds):
    """Drive the scheduler for *seconds* with one active set; returns
    [(tone id, flush)] per chunk."""
    out = []
    for _ in range(int(round(seconds / CHUNK_S))):
        ident, data, flush = s.next_chunk(active)
        out.append((ident, flush))
    return out


def sound_at(s, ident):
    """Is the scheduler inside *ident*'s sound (not its gap)?"""
    return s.current == ident and s.pos <= TONE[ident].sound_frames


# -- CASW-AUR-002: the levels -------------------------------------------------

@pytest.mark.parametrize("level,disc,expect", [
    (0, False, set()), (1, False, set()), (2, False, {C}), (3, False, {W}),
    (0, True, {D}), (1, True, {D}), (2, True, {D, C}), (3, True, {D, W}),
])
def test_tone_per_level_and_none_for_an_advisory(level, disc, expect):
    """CASW-AUR-002 (R4): warning and caution each have a tone, an advisory
    has none, and the disconnect tone is its own, beside the CAS one."""
    assert aural.active_tones(level, disc) == expect


def test_tones_are_distinct_and_fit_their_period():
    """CASW-AUR-002: the three tones differ, each sound ends inside its
    period, and the disconnect sits at warning level."""
    s = tn.Scheduler()
    assert len({s.cycles[i] for i in (D, W, C)}) == 3
    assert TONE[D].level == TONE[W].level == cm.WARNING
    assert TONE[C].level == cm.CAUTION
    for t in tn.TONES:
        assert 0 < t.sound_s < t.period_s
        cyc = s.cycles[t.id]
        assert len(cyc) == 2 * t.period_frames
        # The gap is silent.
        assert set(cyc[2 * (t.sound_frames + 1):]) <= {0}


def test_volume_scales_the_peak():
    """CASW-AUR-002: AuralVolume scales the level; 0 is silent."""
    from array import array
    def peak(v):
        return max(abs(x) for x in array("h", tn.Scheduler(volume=v).cycles[W]))
    assert peak(0.0) == 0
    assert 0.45 * 32767 < peak(0.5) <= 0.5 * 32767
    assert peak(1.0) <= 32767


def test_a_tone_repeats_while_its_condition_holds():
    """CASW-AUR-002: the tone repeats every period until acknowledged."""
    s = tn.Scheduler()
    starts = 0
    for _ in range(int(3 * TONE[C].period_s / CHUNK_S)):
        s.next_chunk({C})
        starts += s.pos == tn.CHUNK_FRAMES
    assert starts == 3


# -- CASW-AUR-003: acknowledge silences ---------------------------------------

def test_acknowledge_stops_the_tone_at_once():
    """CASW-AUR-003 (R5): a tone whose condition goes (acknowledged or
    cleared) stops in the next chunk, mid-sound, and queued audio is
    dropped."""
    s = tn.Scheduler()
    run(s, {W}, 0.05)
    assert sound_at(s, W)
    ident, data, flush = s.next_chunk(set())
    assert (ident, data, flush) == (None, b"", True)
    assert s.next_chunk(set()) == (None, b"", False)


# -- CASW-AUR-004: one at a time, R9 ------------------------------------------

def test_a_warning_interrupts_a_caution_at_once():
    """CASW-AUR-004 (R9): a higher level does not wait."""
    s = tn.Scheduler()
    run(s, {C}, 0.1)
    assert sound_at(s, C)
    ident, _, flush = s.next_chunk({C, W})
    assert (ident, flush) == (W, True)


def test_a_caution_waits_for_every_warning():
    """CASW-AUR-004 (R9): a lower level never plays while a higher one holds,
    gaps included, and starts once the higher one is acknowledged."""
    s = tn.Scheduler()
    chunks = run(s, {W, C}, 5 * TONE[W].period_s)
    assert {i for i, _ in chunks} == {W}
    ident, _, flush = s.next_chunk({C})
    assert (ident, flush) == (C, True)


def test_a_caution_never_interrupts_a_warning():
    """CASW-AUR-004 (R9): a caution arriving mid-warning changes nothing."""
    s = tn.Scheduler()
    run(s, {W}, 0.05)
    pos = s.pos
    ident, _, flush = s.next_chunk({W, C})
    assert (ident, flush, s.pos) == (W, False, pos + tn.CHUNK_FRAMES)


def test_equal_levels_finish_their_sound_and_take_turns():
    """CASW-AUR-004 (R9): the disconnect and a CAS warning are one level. The
    one playing finishes its sound; the other starts in its gap, MIN_GAP_S
    after; then they alternate, so the pilot hears both. Neither is cut."""
    s = tn.Scheduler()
    seq = []
    prev = None
    for _ in range(int(6.0 / CHUNK_S)):
        before = (s.current, s.pos)
        ident, _, flush = s.next_chunk({D, W})
        assert not flush
        if ident != prev:
            if prev is not None:
                # The tone given way to had finished its sound and its gap.
                assert before[1] >= TONE[prev].sound_frames + int(
                    tn.MIN_GAP_S * tn.RATE)
            seq.append(ident)
            prev = ident
    assert seq[:4] == [D, W, D, W]       # disconnect first, then turns


def test_disconnect_alone_holds_the_channel():
    """CASW-AUR-004: with one tone, it simply repeats."""
    s = tn.Scheduler()
    assert {i for i, _ in run(s, {D}, 3.0)} == {D}


def test_unknown_ids_are_ignored():
    s = tn.Scheduler()
    assert s.next_chunk({"nonsense"}) == (None, b"", False)


# -- the player: scheduler to sink --------------------------------------------

class FakeSink:
    def __init__(self, opens=True):
        self.opens = opens
        self.is_open = False
        self.log = []

    def open(self):
        self.is_open = self.opens
        return self.opens

    def write(self, data):
        self.log.append(("write", len(data)))
        return True

    def flush(self):
        self.log.append(("flush",))

    def close(self):
        self.is_open = False


def test_player_writes_and_flushes_through_the_sink(caplog):
    """CASW-AUR-003: the player hands each chunk to the device and drops the
    queue when a tone stops; it logs each change of tone, never per chunk."""
    sink = FakeSink()
    p = aural.AuralPlayer(sink)
    caplog.set_level(logging.INFO, logger=aural.__name__)
    p.set_active({C})
    assert [p.step() for _ in range(3)] == [C, C, C]
    p.set_active(set())
    assert p.step() is None
    assert sink.log == [("write", 2 * tn.CHUNK_FRAMES)] * 3 + [("flush",)]
    assert [r.message for r in caplog.records] == [
        "aural: caution tone", "aural: silent"]


def test_player_thread_with_no_device_never_raises(caplog):
    """CASW-AUR-006: no device: logged, retried, the display runs on."""
    caplog.set_level(logging.WARNING)
    sink = alsa.AlsaSink("pyefis_no_such_device")
    p = aural.AuralPlayer(sink)
    p.set_active({W})
    p.start()
    try:
        assert p._thread.is_alive()
    finally:
        p.stop()
    assert not sink.is_open


# -- the real libasound, into a file PCM -------------------------------------

def _alsa_or_skip():
    if alsa.load_library() is None:
        if os.environ.get("CI"):
            pytest.fail("libasound missing on CI: the ALSA path is untested")
        pytest.skip("libasound not installed")


@pytest.fixture
def tap(tmp_path, monkeypatch):
    """An ALSA config whose device ``tap`` writes every frame it is given to
    a raw file; returns the file path."""
    _alsa_or_skip()
    raw = tmp_path / "tap.raw"
    conf = tmp_path / "asound.conf"
    conf.write_text(
        'pcm.tap {{ type file; slave.pcm "null"; file "{}"; '
        'format "raw" }}\npcm.null {{ type null }}\n'.format(raw))
    monkeypatch.setenv("ALSA_CONFIG_PATH", str(conf))
    return raw


def classify(raw, s):
    """Label each chunk of *raw* with the tone whose cycle it was cut from,
    by matching the bytes against every cycle at chunk offsets."""
    n = 2 * tn.CHUNK_FRAMES
    index = {}
    for ident, cyc in s.cycles.items():
        for off in range(0, len(cyc), n):
            piece = cyc[off:off + n]
            if any(piece):
                index.setdefault(piece, ident)
    out = []
    for off in range(0, len(raw), n):
        piece = raw[off:off + n]
        out.append(index.get(piece, "silence" if not any(piece) else "?"))
    return out


def test_alsa_device_receives_r9_order(tap):
    """CASW-AUR-004, CASW-AUR-003 on the device side: through libasound, a
    caution plays, a warning cuts it off, the caution waits through the
    warning, and nothing follows an acknowledge."""
    sink = alsa.AlsaSink("tap", tn.RATE)
    assert sink.open()
    p = aural.AuralPlayer(sink)
    script = [({C}, 0.2), ({C, W}, 2.5), ({C}, 0.2), (set(), 0.2)]
    for active, secs in script:
        p.set_active(active)
        for _ in range(int(round(secs / CHUNK_S))):
            p.step()
    sink.close()
    got = classify(tap.read_bytes(), p.scheduler)
    assert "?" not in got
    sounding = [g for g in got if g != "silence"]
    runs = [g for i, g in enumerate(sounding) if i == 0 or sounding[i - 1] != g]
    assert runs == [C, W, C]
    # The warning took over 0.2 s in, not after the caution's chime.
    assert got.index(W) == int(round(0.2 / CHUNK_S))


def test_alsa_missing_device_is_logged_once(caplog, tap):
    """CASW-AUR-006: a device that cannot open is one warning, not one per
    retry, and open() never raises."""
    caplog.set_level(logging.WARNING, logger=alsa.__name__)
    sink = alsa.AlsaSink("pyefis_no_such_device")
    assert not sink.open() and not sink.open()
    assert len(caplog.records) == 1
    assert "cannot open ALSA device 'pyefis_no_such_device'" in \
        caplog.records[0].message


# -- CASW-AUR-005: the inputs -------------------------------------------------

def test_aural_level_reads_castop(clock=None):
    """CASW-AUR-005: the gateway's CASTOP sets the level; the slots are not
    re-judged."""
    clock = Clock()
    bus = Bus(clock)
    bus.publish(["2|0|NAVFAIL|NAV FAIL|"])
    bus.items["CASTOP"].value = 2
    m = make(bus, clock)
    assert m.aural_level() == cm.CAUTION
    bus.items["CASTOP"].value = 0      # acknowledged on another display
    assert m.aural_level() == 0
    bus.items["CASTOP"].value = 9      # out of range: never above warning
    assert m.aural_level() == cm.WARNING


def test_link_loss_sounds_the_local_warning_not_a_stale_castop():
    """CASW-AUR-005 (C4): during link loss CASTOP is not read; the local
    GATEWAY LINK LOST sounds until acknowledged here."""
    clock = Clock()
    bus = Bus(clock)
    bus.items["CASTOP"].value = 2
    link = {"lost": False}
    m = make(bus, clock, link=lambda: link["lost"])
    link["lost"] = True
    for k in cm.LIST_KEYS:
        bus.flag(k, fail=True)
    m.poll()
    assert m.aural_level() == cm.WARNING
    m.acknowledge()
    assert m.aural_level() == 0


def test_cas_fail_sounds_the_caution():
    """CASW-AUR-005: CAS FAIL, a local caution, sounds the caution tone."""
    clock = Clock()
    bus = Bus(clock)
    m = make(bus, clock)
    bus.flag("CASSEQ", old=True)
    m.poll()
    assert [x.id for x in m.messages()] == [cm.CAS_FAIL_ID]
    assert m.aural_level() == cm.CAUTION


class FakeAP:
    disconnected = False


class FakePolled:
    def __init__(self, level):
        self.level = level

    def poll(self):
        return self

    def aural_level(self):
        return self.level


def _player(qtbot, cas_on_panel=True, level=0, lookup=None):
    sink = FakeSink()
    ap = FakeAP()
    tp = aural.TonePlayer(cas_on_panel=cas_on_panel, sink=sink, ap=ap,
                          cas_model=FakePolled(level),
                          lookup=lookup or (lambda k: (_ for _ in ()).throw(
                              KeyError(k))),
                          start=False)
    return tp, ap


def test_player_follows_castop_and_the_disconnect(qtbot):
    """CASW-AUR-005: the tone set follows the inputs each poll."""
    tp, ap = _player(qtbot, level=2)
    assert tp.poll() == {C}
    ap.disconnected = True
    assert tp.poll() == {C, D}
    tp._cas_model.level = 0
    ap.disconnected = False
    assert tp.poll() == set()
    assert tp.player.active == frozenset()


def test_no_cas_on_panel_or_bus_means_no_cas_tone(qtbot):
    """CASW-AUR-005: a panel and gateway without CAS never sound CAS FAIL,
    but the disconnect tone still works."""
    tp, ap = _player(qtbot, cas_on_panel=False, level=2)
    assert tp.poll() == set()
    ap.disconnected = True
    assert tp.poll() == {D}


def test_cas_live_on_the_bus_turns_its_tones_on_for_good(qtbot):
    """CASW-AUR-005: with no CAS widget, a good CASSEQ turns CAS tones on, and
    a later loss of the list keeps them on, so CAS FAIL is heard."""
    item = type("I", (), {"old": False, "bad": False, "fail": False})()
    tp, ap = _player(qtbot, cas_on_panel=False, level=2,
                     lookup=lambda k: item)
    assert tp.poll() == {C}
    item.old = True
    assert tp.poll() == {C}


# -- the disconnect input: one rule with the mode strip ------------------------

@pytest.fixture
def ap_keys(fix):
    for key, dtype, lo, hi, tol in AFC1_KEYS:
        fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
        item = fix.db.get_item(key)
        item.value = INITIAL[dtype]
        item.old = item.bad = item.fail = False
    return fix


def test_disconnect_input_is_the_mode_strips_rule(ap_keys, qtbot):
    """CASW-AUR-005: the tone sounds on APDISC exactly when the mode strip
    flashes its red AP: set on a fresh reading, not when the data is old."""
    from pyefis.instruments.autopilot import fma, state
    ap = state.APState()
    strip = fma.FMAModel(ap, {})
    for disc, old in [(False, False), (True, False), (True, True)]:
        ap_keys.db.get_item("APDISC").value = disc
        ap_keys.db.get_item("APENG").old = old
        assert ap.disconnected == strip.disconnect == (disc and not old)


# -- CASW-AUR-006: start-up from the main config -------------------------------

def test_gui_starts_the_player_from_the_main_config(ap_keys, qtbot):
    """CASW-AUR-001, CASW-AUR-006: with a CAS widget on the panel, gui.py
    builds the player at once through the instrument table, with AuralDevice
    and AuralVolume from the main config; a device that cannot open is
    logged and boot goes on."""
    from pyefis import gui
    w = gui._TonePlayerWatch({"AuralDevice": "pyefis_no_such_device",
                              "AuralVolume": 0.5}, {"PFD": 1})
    tp = w.player
    try:
        assert isinstance(tp, aural.TonePlayer)
        assert tp.parent() is None
        assert tp.player.sink.device == "pyefis_no_such_device"
        assert tp.cas_live.on
        from array import array
        assert max(array("h", tp.player.scheduler.cycles[W])) <= 0.5 * 32767
    finally:
        w.stop()


def test_gui_waits_for_cas_or_autopilot_before_loading_the_player(fix, qtbot):
    """CASW-AUR-006: with no CAS widget, the player (not core) is not built
    until CASSEQ or APDISC is read good, so a core-only boot never loads
    it."""
    from pyefis import gui
    w = gui._TonePlayerWatch({"AuralDevice": "pyefis_no_such_device"}, {})
    try:
        w.check()
        assert w.player is None
        fix.db.define_item("APDISC", "APDISC", "bool", None, None, "", 2000,
                           "")
        item = fix.db.get_item("APDISC")
        item.old = item.bad = item.fail = False
        w.check()
        assert isinstance(w.player, aural.TonePlayer)
        assert not w.player.cas_live.on
    finally:
        w.stop()


def test_gui_aural_off_builds_nothing(qtbot):
    """CASW-AUR-006: AuralEnabled false: no player, no watch timer."""
    from pyefis import gui
    w = gui._TonePlayerWatch({"AuralEnabled": False}, {"PFD": 1})
    assert w.player is None and w._timer is None


def test_gui_player_fault_never_reaches_boot(qtbot, monkeypatch, caplog):
    """CASW-AUR-006: a fault building the player costs the tones only."""
    from pyefis import gui

    def boom(*a, **k):
        raise RuntimeError("no")
    monkeypatch.setattr(gui.instrument_table, "instrument", lambda n: boom)
    w = gui._TonePlayerWatch({}, {"PFD": 1})
    assert w.player is None
    assert "alerts are visual only" in caplog.text
