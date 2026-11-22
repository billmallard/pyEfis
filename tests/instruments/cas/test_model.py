#  SPDX-License-Identifier: GPL-2.0-or-later
"""The CAS list model (CAS3, docs/cas_widget_spec.md).

Each test names the requirement it verifies. The model is Qt-free, so these
drive it with fake FIX items and a fake clock; the widget tests cover what is
painted and what a touch writes.
"""

import pytest

from pyefis.instruments.cas import model as cm


class Item:
    """A FIX item as the CAS model reads it: value, flags, age (ms), and
    output_value() recording what would go to the gateway."""

    def __init__(self, key, value, clock):
        self.key = key
        self._value = value
        self.old = False
        self.bad = False
        self.fail = False
        self.clock = clock
        self.stamp = clock.t
        self.sent = []

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, x):
        self._value = x
        self.stamp = self.clock.t

    @property
    def age(self):
        return (self.clock.t - self.stamp) * 1000.0

    def output_value(self):
        self.sent.append(self._value)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Bus:
    """The CAS keys of a running gateway, with helpers to publish a list the
    way the plugin does: slots, then CASCNT/CASTOP, then CASSEQ last."""

    def __init__(self, clock, keys=None):
        self.clock = clock
        self.items = {}
        for k in (keys if keys is not None else cm.LIST_KEYS + (cm.ACK_KEY,)):
            init = "" if k.startswith("CASMSG") else 0
            self.items[k] = Item(k, init, clock)
        self.seq = 0

    def lookup(self, key):
        return self.items[key]

    def publish(self, slots, count=None, seq=None):
        slots = list(slots) + [""] * (cm.SLOTS - len(slots))
        for key, value in zip(cm.SLOT_KEYS, slots):
            self.items[key].value = value
        self.items["CASCNT"].value = (count if count is not None
                                      else sum(1 for s in slots if s))
        self.seq = seq if seq is not None else self.seq + 1
        self.items["CASSEQ"].value = self.seq

    def refresh(self):
        """The plugin's once-a-second rewrite: same values, new stamps."""
        for item in self.items.values():
            if item.key != cm.ACK_KEY:
                item.value = item.value

    def flag(self, key, **flags):
        for name, v in flags.items():
            setattr(self.items[key], name, v)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def bus(clock):
    return Bus(clock)


def make(bus, clock, link=None, status=None, past_grace=True):
    state = {"link": False}
    m = cm.CASModel(bus.lookup,
                    link_lost=link or (lambda: state["link"]),
                    status=status or (lambda: None), clock=clock)
    if past_grace:
        clock.t += cm.BOOT_GRACE_S
        bus.refresh()
        m.poll()
    return m


def lines(m):
    return [(x.level, x.acked, x.id, x.line) for x in m.messages()]


# -- CASW-SRC-001: the slot grammar ------------------------------------------

@pytest.mark.parametrize("raw,expect", [
    ("3|0|APLINK|AP LINK LOST|", (3, False, "APLINK", "AP LINK LOST", "")),
    ("2|1|NAVFAIL|NAV FAIL|", (2, True, "NAVFAIL", "NAV FAIL", "")),
    ("1|0|FPL|FPL MSG|BAD LEG", (1, False, "FPL", "FPL MSG", "BAD LEG")),
])
def test_slot_parses(raw, expect):
    """CASW-SRC-001: LEVEL|ACK|ID|TEXT|DETAIL as fix-gateway cas.yaml writes it."""
    m = cm.parse_slot(raw)
    assert (m.level, m.acked, m.id, m.text, m.detail) == expect


@pytest.mark.parametrize("raw", [
    "", None, "3|0|X|TEXT", "3|0|X|TEXT||extra", "4|0|X|TEXT|",
    "0|0|X|TEXT|", "3|2|X|TEXT|", "3|0|X||", "warning|0|X|T|",
])
def test_bad_slot_is_dropped(raw):
    """CASW-SRC-001: an empty or malformed slot is no message; nothing is
    guessed from it."""
    assert cm.parse_slot(raw) is None


def test_malformed_slot_is_dropped_and_logged(bus, clock, caplog):
    """CASW-SRC-001: a malformed slot among good ones is dropped with an error
    naming the key, and the good ones are shown."""
    bus.publish(["2|0|NAVFAIL|NAV FAIL|", "garbage"])
    m = make(bus, clock)
    assert [x.id for x in m.messages()] == ["NAVFAIL"]
    assert "CASMSG2" in caplog.text


# -- CASW-SRC-002: one list, read in one piece --------------------------------

def test_list_changing_mid_read_keeps_the_last_whole_list(bus, clock):
    """CASW-SRC-002: CASSEQ is written after the slots. If it moves between the
    reads before and after the slots, the read is discarded and the last
    whole list stays, so a half-written list is never drawn."""
    bus.publish(["2|0|A|ALPHA|"])
    m = make(bus, clock)
    assert m.seq == bus.seq
    first = lines(m)

    real = bus.items["CASMSG12"]

    class Racing(Item):
        @property
        def value(self):
            bus.items["CASSEQ"].value = bus.seq + 1   # a write lands now
            return real.value

    bus.items["CASMSG12"] = Racing("CASMSG12", "", clock)
    m._items.pop("CASMSG12")
    bus.items["CASMSG1"].value = "3|0|B|BRAVO|"
    m.poll()
    assert lines(m) == first


def test_count_includes_messages_beyond_slot_12(bus, clock):
    """CASW-SRC-002: CASCNT counts every active message, including those the
    twelve slots cannot hold."""
    bus.publish(["1|0|A{}|ADV {}|".format(i, i) for i in range(12)], count=15)
    m = make(bus, clock)
    assert len(m.messages()) == 12
    assert m.count() == 15


# -- CASW-ORD-001: priority order ---------------------------------------------

def test_order_is_level_then_unacknowledged_then_gateway_order(bus, clock):
    """CASW-ORD-001 (brief 5.2): warnings, cautions, advisories; within a level
    unacknowledged first; the gateway's newest-first order kept inside each."""
    bus.publish(["3|0|W2|W NEW|", "3|0|W1|W OLD|", "3|1|W0|W ACKED|",
                 "2|0|C1|C ONE|", "1|1|A1|A ONE|"])
    m = make(bus, clock)
    assert [x.id for x in m.messages()] == ["W2", "W1", "W0", "C1", "A1"]


def test_local_alert_leads_its_level(bus, clock):
    """CASW-ORD-001: a local alert sorts with its level and ahead of gateway
    lines of that level (it is about the alerting system itself)."""
    bus.publish(["1|0|A1|GW ADVISORY|", "2|0|C1|GW CAUTION|"])
    m = make(bus, clock, status=lambda: {"packs": [
        {"id": "catalog", "status": "CATALOG REFUSED"}]})
    assert [x.id for x in m.messages()] == ["C1", cm.CATALOG_ID, "A1"]


# -- CASW-LOC-001: GATEWAY LINK LOST ------------------------------------------

def test_link_lost_is_a_warning_and_hides_the_gateway_list(bus, clock):
    """CASW-LOC-001, CASW-STALE-001 (brief 6.4, C4): the watchdog trips;
    GATEWAY LINK LOST (warning) is shown and no gateway message is."""
    bus.publish(["2|0|NAVFAIL|NAV FAIL|", "1|0|X|SOMETHING|"])
    link = {"lost": False}
    m = make(bus, clock, link=lambda: link["lost"])
    assert len(m.messages()) == 2
    link["lost"] = True
    for k in cm.LIST_KEYS:             # the watchdog's mark_all_fail
        bus.flag(k, fail=True)
    m.poll()
    assert lines(m) == [(3, False, cm.LINK_LOST_ID, "GATEWAY LINK LOST")]
    assert m.local_only and m.count() == 1 and m.top_level() == cm.WARNING


def test_link_lost_does_not_also_raise_cas_fail(bus, clock):
    """CASW-LOC-002: CAS FAIL means "the gateway answers but the list is lost";
    during link loss the link alert alone says why."""
    m = make(bus, clock, link=lambda: True)
    for k in cm.LIST_KEYS:
        bus.flag(k, fail=True)
    clock.t += 10
    m.poll()
    assert [x.id for x in m.messages()] == [cm.LINK_LOST_ID]


def test_link_alert_replaces_a_cas_fail_at_once(bus, clock):
    """CASW-LOC-002, CASW-LOC-001: in a gateway hang the list can go stale
    before the watchdog trips. When the link alert comes, CAS FAIL goes at
    once, without its clear delay: one loss, one cause on the glass."""
    link = {"lost": False}
    m = make(bus, clock, link=lambda: link["lost"])
    bus.flag("CASSEQ", old=True)
    m.poll()
    assert [x.id for x in m.messages()] == [cm.CAS_FAIL_ID]
    link["lost"] = True
    clock.t += 0.1
    m.poll()
    assert [x.id for x in m.messages()] == [cm.LINK_LOST_ID]


def test_stale_threshold_is_above_the_watchdogs_worst_case():
    """CASW-LOC-002: STALE_S exceeds the watchdog's worst trip time after the
    last list rewrite (1 s rewrite period + timeout + one poll interval), so
    a hang shows GATEWAY LINK LOST first, not CAS FAIL."""
    from pyefis import fix_watchdog
    worst = 1.0 + fix_watchdog.DEFAULT_TIMEOUT_S + fix_watchdog.DEFAULT_INTERVAL_S
    assert cm.STALE_S > worst


def test_link_recovery_waits_the_clear_delay(bus, clock):
    """CASW-LOC-005 (C6): the link alert, and the local-only window, stay
    LOCAL_CLEAR_S after the link returns, so an intermittent link does not
    flap the line or flash the old list back for a moment."""
    bus.publish(["2|0|NAVFAIL|NAV FAIL|"])
    link = {"lost": True}
    m = make(bus, clock, link=lambda: link["lost"])
    assert m.local_only
    link["lost"] = False
    clock.t += 0.5
    bus.refresh()
    m.poll()
    assert [x.id for x in m.messages()] == [cm.LINK_LOST_ID]
    clock.t += cm.LOCAL_CLEAR_S
    bus.refresh()
    m.poll()
    assert [x.id for x in m.messages()] == ["NAVFAIL"]


def test_link_flapping_inside_the_delay_is_one_alert(bus, clock):
    """CASW-LOC-005: 1 s on, 1 s off: one continuous GATEWAY LINK LOST, its
    acknowledge kept, never removed and re-raised."""
    link = {"lost": True}
    m = make(bus, clock, link=lambda: link["lost"])
    m.acknowledge()
    for i in range(10):
        link["lost"] = not link["lost"]
        clock.t += 1.0
        bus.refresh()
        m.poll()
        assert lines(m) == [(3, True, cm.LINK_LOST_ID, "GATEWAY LINK LOST")]


# -- CASW-LOC-002: CAS FAIL ---------------------------------------------------

@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
@pytest.mark.parametrize("key", ["CASMSG1", "CASMSG12", "CASCNT", "CASTOP",
                                 "CASSEQ"])
def test_cas_fail_on_any_list_key_flagged(bus, clock, key, flag):
    """CASW-LOC-002, CASW-STALE-001: any list key old, bad or failed is CAS FAIL
    (caution), and the old list is no longer shown."""
    bus.publish(["2|0|NAVFAIL|NAV FAIL|", "1|0|X|SOMETHING|"])
    m = make(bus, clock)
    bus.flag(key, **{flag: True})
    m.poll()
    assert lines(m) == [(2, False, cm.CAS_FAIL_ID, "CAS FAIL")]


def test_cas_fail_when_the_list_stops_being_rewritten(bus, clock):
    """CASW-LOC-002: with no flag at all (a gateway that stopped sending while
    the link watchdog is off), a list not rewritten for STALE_S is CAS FAIL."""
    bus.publish(["2|0|NAVFAIL|NAV FAIL|"])
    m = make(bus, clock)
    clock.t += cm.STALE_S - 0.1
    m.poll()
    assert [x.id for x in m.messages()] == ["NAVFAIL"]
    clock.t += 0.2
    m.poll()
    assert [x.id for x in m.messages()] == [cm.CAS_FAIL_ID]


def test_cas_fail_when_the_keys_are_not_defined(clock):
    """CASW-LOC-002: a gateway without database/cas.yaml has no CAS: past the
    boot grace that is CAS FAIL, not an empty (quiet-looking) window."""
    bus = Bus(clock, keys=())
    m = make(bus, clock)
    assert [x.id for x in m.messages()] == [cm.CAS_FAIL_ID]


def test_no_cas_fail_inside_the_boot_grace(clock):
    """CASW-LOC-002: at display start the client is still defining items, each
    bad and failed until its first report; that is not CAS FAIL yet."""
    bus = Bus(clock)
    for k in cm.LIST_KEYS:
        bus.flag(k, bad=True, fail=True)
    m = make(bus, clock, past_grace=False)
    assert m.messages() == []
    clock.t += cm.BOOT_GRACE_S
    m.poll()
    assert [x.id for x in m.messages()] == [cm.CAS_FAIL_ID]


def test_cas_fail_clears_after_its_delay_and_the_list_returns(bus, clock):
    """CASW-LOC-002, CASW-LOC-005: the plugin restarts; CAS FAIL clears
    LOCAL_CLEAR_S after the keys are good, then the new list shows."""
    m = make(bus, clock)
    bus.flag("CASSEQ", old=True)
    m.poll()
    assert [x.id for x in m.messages()] == [cm.CAS_FAIL_ID]
    bus.flag("CASSEQ", old=False)
    bus.publish(["2|0|NAVFAIL|NAV FAIL|"])
    m.poll()
    assert [x.id for x in m.messages()] == [cm.CAS_FAIL_ID]
    clock.t += cm.LOCAL_CLEAR_S
    bus.refresh()
    m.poll()
    assert [x.id for x in m.messages()] == ["NAVFAIL"]


def test_cas_fail_with_two_messages_shows_neither(bus, clock):
    """CASW-STALE-001 (bench step 16, C4): two messages active, the plugin
    stops; CAS FAIL, and neither old message is shown as current."""
    bus.publish(["3|0|APLINK|AP LINK LOST|", "2|0|NAVFAIL|NAV FAIL|"])
    m = make(bus, clock)
    assert m.count() == 2
    for k in cm.LIST_KEYS:
        bus.flag(k, old=True)
    m.poll()
    assert lines(m) == [(2, False, cm.CAS_FAIL_ID, "CAS FAIL")]
    assert m.count() == 1 and m.seq is None


# -- CASW-LOC-003: CATALOG REFUSED --------------------------------------------

def test_catalog_refused_from_status_json(bus, clock):
    """CASW-LOC-003: the CERT3 rollback row in status.json raises CATALOG
    REFUSED (advisory); without it, nothing."""
    status = {"s": {"ok": True, "packs": [{"id": "nasr", "status": "CURRENT"}]}}
    m = make(bus, clock, status=lambda: status["s"])
    assert m.messages() == []
    status["s"]["packs"].insert(0, {"id": "catalog",
                                    "status": "CATALOG REFUSED"})
    m.poll()
    assert lines(m) == [(1, False, cm.CATALOG_ID, "CATALOG REFUSED")]
    status["s"] = None
    m.poll()
    assert m.messages() == []


@pytest.mark.parametrize("status", [None, [], "x", {"packs": "x"},
                                    {"packs": [None, 3]}, {"ok": False}])
def test_catalog_refused_reads_defensively(status):
    """CASW-LOC-003: an unexpected status.json shape is "no refusal"."""
    assert cm.catalog_refused(status) is False


def test_catalog_refused_shows_during_link_loss(bus, clock):
    """CASW-LOC-003, CASW-STALE-001: local alerts are what the window holds when
    the gateway list is unknown."""
    m = make(bus, clock, link=lambda: True,
             status=lambda: {"packs": [{"status": "CATALOG REFUSED"}]})
    assert [x.id for x in m.messages()] == [cm.LINK_LOST_ID, cm.CATALOG_ID]


# -- CASW-ACK-001: acknowledge ------------------------------------------------

def test_acknowledge_writes_the_drawn_sequence(bus, clock):
    """CASW-ACK-001 (brief 6.5): a touch writes CASACK = the CASSEQ of the list
    drawn, and sends it to the gateway."""
    bus.publish(["2|0|NAVFAIL|NAV FAIL|"], seq=41)
    m = make(bus, clock)
    assert m.acknowledge() is True
    assert bus.items[cm.ACK_KEY].sent == [41]


def test_acknowledge_never_names_a_list_newer_than_the_drawn_one(bus, clock):
    """CASW-ACK-001 (C3): a message published after the last poll is not
    acknowledged by a touch on the older list."""
    bus.publish(["2|0|NAVFAIL|NAV FAIL|"], seq=7)
    m = make(bus, clock)
    bus.publish(["3|0|APLINK|AP LINK LOST|", "2|0|NAVFAIL|NAV FAIL|"], seq=8)
    m.acknowledge()
    assert bus.items[cm.ACK_KEY].sent == [7]


def test_nothing_written_when_everything_is_acknowledged(bus, clock):
    """CASW-ACK-001: with every gateway line acknowledged a touch writes
    nothing (it opens the full list instead, in the widget)."""
    bus.publish(["2|1|NAVFAIL|NAV FAIL|"])
    m = make(bus, clock)
    assert m.acknowledge() is False
    assert bus.items[cm.ACK_KEY].sent == []


def test_acknowledge_during_link_loss_is_local_only(bus, clock):
    """CASW-ACK-001, CASW-STALE-001: during link loss a touch acknowledges the
    local alert here and writes nothing to a gateway it cannot see."""
    m = make(bus, clock, link=lambda: True)
    assert m.acknowledge() is True
    assert lines(m) == [(3, True, cm.LINK_LOST_ID, "GATEWAY LINK LOST")]
    assert bus.items[cm.ACK_KEY].sent == []


def test_local_alert_re_raised_is_unacknowledged(bus, clock):
    """CASW-ACK-001: an acknowledged local alert that clears and comes back is
    a new alert and flashes again."""
    status = {"s": {"packs": [{"status": "CATALOG REFUSED"}]}}
    m = make(bus, clock, status=lambda: status["s"])
    m.acknowledge()
    assert m.messages()[0].acked
    status["s"] = None
    m.poll()
    status["s"] = {"packs": [{"status": "CATALOG REFUSED"}]}
    m.poll()
    assert not m.messages()[0].acked


def test_acknowledge_without_a_casack_key_is_harmless(clock):
    """CASW-ACK-001: a gateway with the list but no CASACK: the touch writes
    nothing and does not raise."""
    bus = Bus(clock, keys=cm.LIST_KEYS)
    bus.publish(["2|0|NAVFAIL|NAV FAIL|"])
    m = make(bus, clock)
    assert m.acknowledge() is False


# -- CASW-WIN-001: quiet ------------------------------------------------------

def test_quiet_list_is_empty(bus, clock):
    """CASW-WIN-001 (bench step 1): CASCNT 0, nothing to draw, level 0."""
    bus.publish([])
    m = make(bus, clock)
    assert m.messages() == [] and m.count() == 0 and m.top_level() == 0
    assert not m.unacked() and not m.local_only
