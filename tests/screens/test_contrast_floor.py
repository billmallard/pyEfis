"""
Contrast floor for what we ship: the pyEfis#139 class, generalized (AER-4331).

#139 shipped invisible tab labels -- black ``WindowText`` on a black
``Window`` -- and 630 tests missed it, because every other widget paints with
an explicit QPainter pen and nothing had ever depended on palette foreground
roles. AER-664 (PR #177) fixed that instance. This module is the guard for the
class:

1. Token pairs: for every shipped theme, each text-on-surface colour pair --
   registry defaults, the palette a ``Screen`` applies, and the few surfaces
   a widget hardcodes -- clears a WCAG 2.x contrast floor.
2. Render check: under ``QT_QPA_PLATFORM=offscreen``, stock Qt controls
   parented to a real ``Screen`` actually paint visible text with the palette
   that ``Screen`` applies. This is the half that fails on the pre-AER-664
   tree.

Scope (Bill, 2026-09-06): this tests OUR shipped defaults and themes, never a
builder's choices. It is a CI gate on what we publish. A builder may set any
colour they like; nothing here reads or warns about a user config.

Themes: until the colour-token work (BACKLOG S1) lands, the theme cascade in
``preferences.yaml`` carries no colour at all, so there is exactly one
effective shipped theme -- the registry defaults on each shipped
``screenColor``. ``test_shipped_preferences_carry_no_colour_yet`` fails the
moment a colour key appears there, so S1 cannot land without extending
``_shipped_themes()`` to resolve its tokens through this floor.
"""
import glob
import os

import pytest
import yaml
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton,
    QTabBar, QWidget,
)

from pyefis.screens.screenbuilder import Screen


CONFIG_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pyefis", "config")

# WCAG 2.x success criteria 1.4.3 (text, AA) and 1.4.11 (non-text graphics).
TEXT_FLOOR = 4.5
GRAPHIC_FLOOR = 3.0


# ── Contrast arithmetic (WCAG 2.x relative luminance) ─────────────────────────

def _relative_luminance(color):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(color.red()) + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue()))


def contrast_ratio(a, b):
    la, lb = _relative_luminance(QColor(a)), _relative_luminance(QColor(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_contrast_ratio_matches_wcag_reference_values():
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#000000", "#000000") == pytest.approx(1.0)
    # WCAG's own worked boundary: #767676 on white is the darkest grey to
    # pass AA text at 4.5:1.
    assert contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)


# ── What we ship ──────────────────────────────────────────────────────────────

def _shipped_screen_colors():
    """Every ``screenColor`` set anywhere in the shipped config tree. The
    string form ``"(r,g,b)"`` is what YAML hands back (see default.yaml)."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "screenColor" and value is not None:
                    found.add(str(value).replace(" ", ""))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in glob.glob(os.path.join(CONFIG_DIR, "**", "*.yaml"),
                          recursive=True):
        with open(path) as f:
            try:
                walk(yaml.safe_load(f))
            except yaml.YAMLError:
                continue
    return sorted(found)


def _colour_keys(node, path=""):
    """Every key in a YAML subtree that names a colour."""
    hits = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            k = str(key).lower()
            if "color" in k or "colour" in k:
                hits.append(here)
            hits.extend(_colour_keys(value, here))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            hits.extend(_colour_keys(item, f"{path}[{i}]"))
    return hits


def test_shipped_preferences_carry_no_colour_yet():
    """Tripwire for BACKLOG S1. The pair table below resolves colour from the
    registry only, which is correct while the theme cascade carries no colour.
    When a ``colors:`` block or any colour option appears in the shipped
    preferences, those values become a shipped theme this floor does not yet
    see -- extend ``_shipped_themes()`` to resolve them, then update this
    test."""
    with open(os.path.join(CONFIG_DIR, "preferences.yaml")) as f:
        prefs = yaml.safe_load(f)
    assert _colour_keys(prefs) == [], (
        "shipped preferences now carry colour; resolve them in "
        "_shipped_themes() so the contrast floor covers every shipped theme")


def _shipped_themes():
    """(theme name, {type: {colour prop: value}}) for every shipped theme.

    One today: the registry defaults (see the module docstring)."""
    from pyefis.screens.screenbuilder_factory import REGISTRY
    defaults = {
        t: {p.name: p.default for p in spec.properties if p.kind == "color"}
        for t, spec in REGISTRY.items()
    }
    return [("default", defaults)]


# Text-on-surface pairs, per instrument type: (ink, surface, floor). Each end
# is a colour prop name on that type, or "#rrggbb" for a colour the widget
# itself hardcodes (cited). A prop default of None means "inherit the Screen
# palette", which the palette and render checks below cover.
PAIRS = {
    "button": [("fg_color", "bg_color", TEXT_FLOOR)],
    "heading_display": [("fg_color", "bg_color", TEXT_FLOOR)],
    "value_text": [
        ("value_color", "bg_color", TEXT_FLOOR),
        ("prefix_color", "bg_color", TEXT_FLOOR),
        ("border_color", "bg_color", GRAPHIC_FLOOR),
    ],
    # Tape numerals are hardcoded white (vsi/__init__.py, Alt_Trend_Tape).
    "altimeter_trend_tape": [("#ffffff", "bg_color", TEXT_FLOOR)],
    # Selected-altitude readout text over the tape's black ground
    # (altimeter/altsel.py; Altimeter_Tape bg defaults to black).
    "altimeter_tape": [("alt_bug_color", "#000000", TEXT_FLOOR)],
    "horizontal_situation_indicator": [
        ("fg_color", "bg_color", TEXT_FLOOR),
        ("needle_color", "bg_color", GRAPHIC_FLOOR),
        ("course_color", "bg_color", GRAPHIC_FLOOR),
        ("vloc_color", "bg_color", GRAPHIC_FLOOR),
        ("heading_bug_color", "bg_color", GRAPHIC_FLOOR),
        ("track_color", "bg_color", GRAPHIC_FLOOR),
        ("bearing_color", "bg_color", GRAPHIC_FLOOR),
    ],
    # checklist, nav_status and flight_plan fill their own face #000000
    # (checklist/__init__.py, nav_status/__init__.py, flight_plan/__init__.py)
    # and draw their colour props on it. The checklist's current row inverts:
    # black text on a current_color fill.
    "checklist": [
        ("text_color", "#000000", TEXT_FLOOR),
        ("response_color", "#000000", TEXT_FLOOR),
        ("done_color", "#000000", TEXT_FLOOR),
        ("section_color", "#000000", TEXT_FLOOR),
        ("#000000", "current_color", TEXT_FLOOR),
    ],
    "nav_status": [
        ("text_color", "#000000", TEXT_FLOOR),
        ("active_color", "#000000", TEXT_FLOOR),
    ],
    "flight_plan": [
        ("active_color", "#000000", TEXT_FLOOR),
        ("future_color", "#000000", TEXT_FLOOR),
        ("past_color", "#000000", TEXT_FLOOR),
    ],
}

# Colour props that are not text on a flat surface, with the reason. Their
# ground is sky/terrain/map imagery, so a two-colour ratio does not describe
# what the pilot sees; the props themselves are covered by the style contract.
NOT_A_SURFACE_PAIR = {
    ("atitude_indicator", "symbol_color"): "own-ship symbol over sky/ground",
    ("atitude_indicator", "horizon_heading_color"): "drawn over sky/ground",
    ("virtual_vfr", "symbol_color"): "own-ship symbol over terrain",
    ("virtual_vfr", "horizon_heading_color"): "drawn over terrain",
    ("virtual_vfr", "svs_road_color"): "road fill over terrain",
    ("virtual_vfr", "svs_road_casing_color"): "road casing over terrain",
    ("moving_map", "symbol_color"): "own-ship symbol over the map",
    ("moving_map", "road_color"): "road over map imagery",
    ("moving_map", "road_casing_color"): "road casing over map imagery",
    ("moving_map", "river_color"): "river over map imagery",
    # None by default: inherits the Screen palette (covered below).
    ("tab_section", "fg_color"): "inherits the Screen palette",
    ("tab_section", "bg_color"): "inherits the Screen palette",
}


def _resolve(end, colours):
    return end if end.startswith("#") else colours[end]


def test_every_colour_prop_is_classified():
    """A new colour prop must be placed in PAIRS or NOT_A_SURFACE_PAIR -- so a
    widget that adds a text colour cannot ship it past this floor unseen."""
    for _theme, colours in _shipped_themes():
        classified = set(NOT_A_SURFACE_PAIR)
        for t, pairs in PAIRS.items():
            for ink, surface, _floor in pairs:
                for end in (ink, surface):
                    if not end.startswith("#"):
                        classified.add((t, end))
        unclassified = sorted(
            (t, prop) for t, props in colours.items() for prop in props
            if (t, prop) not in classified)
        assert unclassified == [], (
            "colour props with no contrast classification -- add each to "
            f"PAIRS or NOT_A_SURFACE_PAIR: {unclassified}")


def _pair_cases():
    cases = []
    for theme, colours in _shipped_themes():
        for t, pairs in PAIRS.items():
            for ink, surface, floor in pairs:
                cases.append(pytest.param(
                    theme, t, ink, surface, floor, colours.get(t, {}),
                    id=f"{theme}-{t}-{ink}-on-{surface}"))
    return cases


@pytest.mark.parametrize("theme,itype,ink,surface,floor,colours", _pair_cases())
def test_shipped_text_on_surface_pair_clears_the_floor(
        theme, itype, ink, surface, floor, colours):
    ink_c, surface_c = _resolve(ink, colours), _resolve(surface, colours)
    ratio = contrast_ratio(ink_c, surface_c)
    assert ratio >= floor, (
        f"{theme} theme: {itype} {ink}={ink_c} on {surface}={surface_c} is "
        f"{ratio:.2f}:1, below the {floor}:1 floor")


# ── The palette a Screen applies ──────────────────────────────────────────────

class _Parent(QWidget):
    """The slice of gui.Main that Screen.__init__ reads."""

    def __init__(self, screen_color):
        super().__init__()
        self.screenColor = screen_color
        self.nodeID = 1
        self.preferences = {"style": {}, "styles": {}, "gauges": {},
                            "enabled": {}, "includes": {}, "buttons": {}}

    def get_config_item(self, child, key):
        # An empty screen: QWidget.render() flushes the Screen's pending
        # resize, and Screen.resizeEvent builds the screen from this.
        return {"layout": {"rows": 10, "columns": 10}, "instruments": [],
                "encoder": None, "encoder_button": None,
                "encoder_timeout": None}.get(key)

    def getRunningScreen(self):
        return "TEST"


def _screen(qtbot, screen_color):
    parent = _Parent(screen_color)
    qtbot.addWidget(parent)
    screen = Screen(parent)
    qtbot.addWidget(screen)
    return screen


R = QPalette.ColorRole
# The foreground/background role pairs stock Qt controls draw text with.
PALETTE_PAIRS = [
    (R.WindowText, R.Window),      # QLabel, QTabBar, QCheckBox, QGroupBox
    (R.ButtonText, R.Button),      # QPushButton, QToolButton
    (R.Text, R.Base),              # QLineEdit, QComboBox, item views
    pytest.param(
        R.HighlightedText, R.Highlight,
        marks=pytest.mark.xfail(strict=True, reason=(
            "known: Screen leaves Highlight at the Fusion default #308cc6, "
            "3.69:1 under white HighlightedText. No shipped widget paints it "
            "today -- the one selection UI, listbox, overrides it in its "
            "stylesheet -- but a new stock control would inherit it. Fixing "
            "it changes shipped pixels, so it is a separate call (AER-4331). "
            "strict: when Screen sets these roles this flips; drop the mark.")),
        id="HighlightedText-on-Highlight"),
    (R.ToolTipText, R.ToolTipBase),
]


@pytest.mark.parametrize("screen_color", _shipped_screen_colors())
@pytest.mark.parametrize(
    "fg_role,bg_role", PALETTE_PAIRS,
    ids=lambda v: v.name if isinstance(v, QPalette.ColorRole) else None)
def test_screen_palette_pairs_clear_the_floor(
        fix, qtbot, screen_color, fg_role, bg_role):
    palette = _screen(qtbot, screen_color).palette()
    fg, bg = palette.color(fg_role), palette.color(bg_role)
    ratio = contrast_ratio(fg, bg)
    assert ratio >= TEXT_FLOOR, (
        f"screenColor {screen_color}: {fg_role.name} {fg.name()} on "
        f"{bg_role.name} {bg.name()} is {ratio:.2f}:1, below {TEXT_FLOOR}:1")


def test_shipped_screen_colors_were_found():
    """The two tests above are vacuous if the config walk finds nothing."""
    assert _shipped_screen_colors(), "no screenColor found in shipped config"


# ── Render check: stock controls paint visible text ───────────────────────────

SAMPLE = "WWWW8888"


def _label(text):
    return QLabel(text)


def _push_button(text):
    return QPushButton(text)


def _check_box(text):
    return QCheckBox(text)


def _radio_button(text):
    return QRadioButton(text)


def _group_box(text):
    return QGroupBox(text)


def _line_edit(text):
    w = QLineEdit()
    w.setText(text)
    return w


def _tab_bar(text):
    w = QTabBar()
    w.addTab(text)
    return w


STOCK_CONTROLS = [_label, _push_button, _check_box, _radio_button,
                  _group_box, _line_edit, _tab_bar]


def _render(screen, make, text, size=None):
    widget = make(text)
    widget.setParent(screen)
    widget.ensurePolished()
    # A floor size: QGroupBox has no valid sizeHint() outside a layout.
    widget.resize(size or widget.sizeHint().expandedTo(
        widget.minimumSizeHint()).expandedTo(QSize(200, 40)))
    pixmap = QPixmap(widget.size())
    pixmap.fill(screen.palette().color(R.Window))
    widget.render(pixmap)
    image = pixmap.toImage()
    widget.setParent(None)
    widget.deleteLater()
    return image


# A glyph pixel must stand out from what was there without the text by at
# least the non-text floor; anti-aliased edges fall below it, glyph cores do
# not. 20 such pixels is a fraction of one glyph of SAMPLE at any font size.
GLYPH_CONTRAST = GRAPHIC_FLOOR
MIN_GLYPH_PIXELS = 20


@pytest.mark.parametrize("screen_color", _shipped_screen_colors())
@pytest.mark.parametrize("make", STOCK_CONTROLS,
                         ids=[m.__name__.lstrip("_") for m in STOCK_CONTROLS])
def test_stock_control_paints_visible_text(fix, qtbot, screen_color, make):
    """Render the control with and without its text under the palette a real
    Screen applies; the pixels that differ are the glyphs. Style-independent:
    it measures the text against whatever the control painted behind it
    (a button face, a tab, the screen), which is what the pilot reads."""
    screen = _screen(qtbot, screen_color)
    with_text = _render(screen, make, SAMPLE)
    without = _render(screen, make, "", size=with_text.size())

    glyph_pixels = 0
    for y in range(with_text.height()):
        for x in range(with_text.width()):
            a, b = with_text.pixelColor(x, y), without.pixelColor(x, y)
            if a != b and contrast_ratio(a, b) >= GLYPH_CONTRAST:
                glyph_pixels += 1
    assert glyph_pixels >= MIN_GLYPH_PIXELS, (
        f"{make.__name__.lstrip('_')} under screenColor {screen_color}: only "
        f"{glyph_pixels} glyph pixels clear {GLYPH_CONTRAST}:1 against the "
        "control's own background -- its text is effectively invisible")
