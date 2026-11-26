"""INS6 (AER-6684): one FIX flag subscription, in ``BugBinding``.

ARCH3 (section 4.2) counted 44 ``failChanged`` references in ``src/pyefis``,
most of them the same hand-rolled "any flag, repaint" trio. INS6 widened
``BugBinding`` with a ``qualityChanged`` signal and an ``unbind`` and moved
the identical sites onto it; each widget still draws its flags its own way.

The count of hand-rolled sites is pinned per file by the ARCHG4 ratchet
(``tests/arch/test_flag_subscriptions.py``); INS6 lowered it.
"""
import logging

import pytest

from pyefis.instruments.helpers.bugs import BugBinding


class _Recorder:
    def __init__(self, binding):
        self.quality = 0
        self.changed = 0
        binding.qualityChanged.connect(self._q)
        binding.changed.connect(self._c)

    def _q(self):
        self.quality += 1

    def _c(self):
        self.changed += 1


def _fresh(fix, key="NUMOK"):
    item = fix.db.get_item(key)
    item.old = item.bad = item.fail = item.annunciate = False
    return item


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_quality_changed_fires_on_each_flag(fix, flag):
    item = _fresh(fix)
    rec = _Recorder(BugBinding("NUMOK"))
    setattr(item, flag, True)
    assert (rec.quality, rec.changed) == (1, 1)
    setattr(item, flag, False)
    assert (rec.quality, rec.changed) == (2, 2)


def test_quality_changed_ignores_value_and_annunciate(fix):
    """The migrated sites connected old, bad and fail only: a value or an
    annunciate change must not reach them through ``qualityChanged``."""
    item = _fresh(fix)
    rec = _Recorder(BugBinding("NUMOK"))
    item.value = 12.0
    item.annunciate = True
    assert rec.quality == 0
    assert rec.changed == 2


def test_unbind_stops_both_signals(fix):
    item = _fresh(fix)
    binding = BugBinding("NUMOK")
    rec = _Recorder(binding)
    binding.unbind()
    item.value = 13.0
    item.old = True
    item.annunciate = True
    assert (rec.quality, rec.changed) == (0, 0)
    binding.unbind()  # twice is harmless
    assert binding.item is item  # the item stays readable


def test_unbind_leaves_other_subscribers_connected(fix):
    item = _fresh(fix)
    first, second = BugBinding("NUMOK"), BugBinding("NUMOK")
    rec = _Recorder(second)
    first.unbind()
    item.fail = True
    assert rec.quality == 1


def test_missing_key_warns_by_default(fix, caplog):
    with caplog.at_level(logging.WARNING):
        binding = BugBinding("NO_SUCH_KEY")
    assert binding.item is None
    assert "NO_SUCH_KEY" in caplog.text
    binding.unbind()


def test_missing_key_quiet_for_a_caller_with_its_own_message(fix, caplog):
    with caplog.at_level(logging.WARNING):
        binding = BugBinding("NO_SUCH_KEY", warn=False)
    assert binding.item is None
    assert caplog.text == ""
