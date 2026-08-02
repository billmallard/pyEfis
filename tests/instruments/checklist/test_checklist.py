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
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Tests for the interactive checklist instrument (backlog P1.1, CAP-115).

The traversal / acknowledge logic lives in the pure ``ChecklistModel`` and is
tested directly (no Qt); the ``Checklist`` widget tests cover construction,
paint-never-raises, the encoder protocol, and the HMI action set.
"""

import pytest
import pyefis.hmi as hmi
from pyefis.instruments import checklist
from pyefis.instruments.checklist import ChecklistModel
from pyefis.screens import screenbuilder_factory as factory


SAMPLE = [
    {
        "id": "before-takeoff",
        "title": "Before Takeoff",
        "category": "normal",
        "sections": [
            {"title": "Runup", "items": [
                {"text": "Throttle", "response": "1700 RPM"},
                {"text": "Magnetos", "response": "CHECK"},
            ]},
            {"title": "Final", "items": [
                {"text": "Flight controls", "response": "FREE & CORRECT"},
                {"note": "Confirm the runway is clear"},
            ]},
        ],
    },
    {
        "id": "engine-failure",
        "title": "Engine Failure",
        "category": "emergency",
        "items": [
            {"text": "Airspeed", "response": "BEST GLIDE"},
            {"text": "Fuel", "response": "ON"},
        ],
    },
]


# --------------------------------------------------------------------------
# ChecklistModel -- pure logic (no Qt)
# --------------------------------------------------------------------------

def test_load_parses_sets_sections_and_flat_items():
    m = ChecklistModel(SAMPLE)
    assert len(m.checklists) == 2
    active = m.active_checklist()
    assert active["id"] == "before-takeoff"
    assert active["title"] == "Before Takeoff"
    assert active["category"] == "normal"
    kinds = [e["kind"] for e in active["entries"]]
    assert kinds == ["section", "item", "item", "section", "item", "note"]
    # The second checklist uses flat items (no sections).
    assert [e["kind"] for e in m.checklists[1]["entries"]] == ["item", "item"]


def test_selectable_excludes_section_headers():
    m = ChecklistModel(SAMPLE)
    sel = m.selectable()
    assert [e["kind"] for e in sel] == ["item", "item", "item", "note"]
    assert all(e["kind"] != "section" for e in sel)


def test_advance_and_wrap():
    m = ChecklistModel(SAMPLE)
    assert m.current == 0
    m.move(1)
    assert m.current == 1
    m.move(1)
    m.move(1)
    assert m.current == 3            # last selectable (the note)
    m.move(1)
    assert m.current == 0            # wraps forward
    m.move(-1)
    assert m.current == 3            # wraps backward
    # An encoder can send several steps at once.
    m.move(5)
    assert m.current == (3 + 5) % 4


def test_acknowledge_toggle():
    m = ChecklistModel(SAMPLE)
    assert m.progress() == (0, 3)
    m.toggle()                       # Throttle
    assert m.current_entry()["acked"] is True
    assert m.progress() == (1, 3)
    m.toggle()
    assert m.current_entry()["acked"] is False
    assert m.progress() == (0, 3)


def test_toggle_is_a_noop_on_a_note():
    m = ChecklistModel(SAMPLE)
    m.current = 3                    # the informational note
    assert m.current_entry()["kind"] == "note"
    m.toggle()                       # must not raise, must not count
    assert m.progress() == (0, 3)


def test_acknowledge_advance_auto_advances_to_next_unacked():
    m = ChecklistModel(SAMPLE)
    m.acknowledge_advance()          # ack Throttle -> jump to Magnetos
    assert m.current == 1
    m.acknowledge_advance()          # ack Magnetos -> jump to Flight controls
    assert m.current == 2
    m.acknowledge_advance()          # ack last item; no unacked left -> stay
    assert m.current == 2
    assert m.progress() == (3, 3)
    assert m.is_complete() is True


def test_acknowledge_advance_does_not_jump_when_unacknowledging():
    m = ChecklistModel(SAMPLE)
    m.toggle()                       # Throttle acked
    m.acknowledge_advance()          # toggling it back off must not advance
    assert m.current == 0
    assert m.current_entry()["acked"] is False


def test_next_unacked_wraps_and_skips_notes():
    m = ChecklistModel(SAMPLE)
    # Acknowledge Throttle and Flight controls, leave Magnetos unacked.
    m.selectable()[0]["acked"] = True
    m.selectable()[2]["acked"] = True
    m.current = 3                    # sitting on the note
    m.next_unacked()                 # wraps forward, skips the note, finds Magnetos
    assert m.current == 1


def test_reset_active_clears_acks_and_returns_to_top():
    m = ChecklistModel(SAMPLE)
    m.acknowledge_advance()
    m.acknowledge_advance()
    assert m.progress()[0] == 2
    m.reset_active()
    assert m.progress() == (0, 3)
    assert m.current == 0


def test_multi_checklist_selection():
    m = ChecklistModel(SAMPLE)
    m.move(2)                        # not at the top
    m.next_list()
    assert m.active_checklist()["id"] == "engine-failure"
    assert m.current == 0            # switching resets the cursor
    m.prev_list()
    assert m.active_checklist()["id"] == "before-takeoff"
    assert m.select("engine-failure") is True
    assert m.active_checklist()["id"] == "engine-failure"
    assert m.select("does-not-exist") is False
    assert m.active_checklist()["id"] == "engine-failure"


def test_next_list_is_a_noop_with_a_single_checklist():
    m = ChecklistModel([SAMPLE[0]])
    m.next_list()
    assert m.active == 0
    m.prev_list()
    assert m.active == 0


@pytest.mark.parametrize("payload", [None, "garbage", 42, {}, [],
                                     [1, 2, "x"], {"checklists": "nope"}])
def test_empty_and_malformed_construct_never_raises(payload):
    m = ChecklistModel(payload)
    # Every accessor and mutator is total on an empty model.
    assert m.active_checklist() is None
    assert m.current_entry() is None
    assert m.selectable() == []
    assert m.progress() == (0, 0)
    assert m.is_complete() is False
    m.move(1)
    m.move(-3)
    m.toggle()
    m.acknowledge_advance()
    m.next_unacked()
    m.next_list()
    m.prev_list()
    m.reset_active()
    assert m.select("x") is False


def test_set_object_form_is_accepted():
    # The delivered form is a set object, not a bare list.
    m = ChecklistModel({"schema_version": 1, "checklists": SAMPLE})
    assert len(m.checklists) == 2
    assert m.active_checklist()["id"] == "before-takeoff"


def test_malformed_items_are_skipped_but_checklist_survives():
    m = ChecklistModel([
        {"id": "mixed", "title": "Mixed", "items": [
            {"text": "Good", "response": "OK"},
            "not-a-dict",
            {"neither-text-nor-note": True},
            {"note": "Info only"},
        ]},
    ])
    kinds = [e["kind"] for e in m.active_checklist()["entries"]]
    assert kinds == ["item", "note"]
    assert m.progress() == (0, 1)


# --------------------------------------------------------------------------
# Checklist widget -- construction, paint, encoder
# --------------------------------------------------------------------------

def test_widget_constructs_empty_and_paints(qtbot):
    w = checklist.Checklist(None)
    qtbot.addWidget(w)
    w.resize(320, 240)
    assert w.model.active_checklist() is None
    w.grab()                         # forces paintEvent -- must not raise


def test_widget_paints_with_content(qtbot):
    w = checklist.Checklist(None, checklists=SAMPLE)
    qtbot.addWidget(w)
    w.resize(320, 240)
    w.grab()
    w.enc_highlight(True)            # current-row highlight path
    w.model.toggle()                 # an acknowledged row
    w.grab()                         # must not raise


def test_widget_paints_malformed_config(qtbot):
    w = checklist.Checklist(None, checklists="garbage")
    qtbot.addWidget(w)
    w.resize(200, 150)
    w.grab()


def test_encoder_protocol(qtbot):
    w = checklist.Checklist(None, checklists=SAMPLE)
    qtbot.addWidget(w)
    assert w.enc_selectable() is True
    assert w.enc_select() is True    # enters control mode
    assert w.enc_changed(1) is True
    assert w.model.current == 1
    assert w.enc_clicked() is True   # ack current (idx 1) + auto-advance
    assert w.model.selectable()[1]["acked"] is True
    assert w.model.current == 2      # advanced to the next unacked item
    w.enc_highlight(True)
    assert w._selected is True
    w.enc_highlight(False)
    assert w._selected is False


def test_build_via_factory(qtbot):
    w = factory.create_instrument(
        None, {"type": "checklist", "options": {"checklists": SAMPLE}},
        font_family="DejaVu Sans Condensed")
    qtbot.addWidget(w)
    assert isinstance(w, checklist.Checklist)
    assert len(w.model.checklists) == 2


# --------------------------------------------------------------------------
# HMI actions -- a Button / panel key drives the checklist
# --------------------------------------------------------------------------

def test_all_hmi_verbs_registered():
    hmi.initialize({})
    for verb in ("checklist next item", "checklist previous item",
                 "checklist toggle item", "checklist next unacked",
                 "checklist next list", "checklist previous list",
                 "checklist reset"):
        assert verb in hmi.actions.signalMap


def test_hmi_actions_drive_the_widget(qtbot):
    hmi.initialize({})
    w = checklist.Checklist(None, checklists=SAMPLE)
    qtbot.addWidget(w)

    hmi.actions.trigger("checklist next item", "")
    assert w.model.current == 1
    hmi.actions.trigger("checklist previous item", "")
    assert w.model.current == 0

    hmi.actions.trigger("checklist toggle item", "")
    assert w.model.selectable()[0]["acked"] is True

    hmi.actions.trigger("checklist next unacked", "")
    assert w.model.current == 1      # skipped the acked Throttle

    hmi.actions.trigger("checklist next list", "")
    assert w.model.active_checklist()["id"] == "engine-failure"
    hmi.actions.trigger("checklist previous list", "")
    assert w.model.active_checklist()["id"] == "before-takeoff"

    hmi.actions.trigger("checklist reset", "")
    assert w.model.progress() == (0, 3)
    assert w.model.current == 0


def test_hmi_group_targeting(qtbot):
    hmi.initialize({})
    w = checklist.Checklist(None, checklists=SAMPLE)
    qtbot.addWidget(w)
    w.hmi_group = "left"

    hmi.actions.trigger("checklist next item", "right")   # not us
    assert w.model.current == 0
    hmi.actions.trigger("checklist next item", "left")    # addressed to us
    assert w.model.current == 1
    hmi.actions.trigger("checklist next item", "")        # broadcast
    assert w.model.current == 2
    hmi.actions.trigger("checklist next item", "*")       # broadcast
    assert w.model.current == 3
