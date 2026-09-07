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

"""tab_section -- an in-screen container instrument (pyEfis#131 / AER-172).

Occupies one section of a screen, like any other instrument, and lets the
pilot/config switch between named tab-views inside that section, each holding
its own real instruments. Distinct from the whole-screen switching in
gui.Main.showScreen (pyEfis#72) -- that swaps entire authored screens; this is
one container among many instruments on a single screen.

v1 scope (see pyEfis#131 "Open questions -- RESOLVED"):
  * touch/click tab bar only -- no hardware-button switching yet;
  * reload/power-up always lands on the configured ``default_tab``, not the
    last-selected tab (no runtime persistence);
  * a tab_section cannot be nested inside another tab_section.

Each tab's nested ``instruments:`` list is built through the exact same
``Screen`` (screenbuilder.py) that a top-level screen uses -- the tab content
widget below *is* a ``Screen`` instance, constructed from an explicit config
dict (``layout`` + ``instruments``, the same two keys a screen's own YAML
carries) rather than looked up by name via gui.Main. This reuses grid layout,
create_instrument() dispatch, and option application unchanged; there is
nothing tab_section-specific about how a tab's contents get built or resized.
"""

import logging

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QTabBar, QStackedWidget

logger = logging.getLogger(__name__)

# A dropped-fresh container should never be in an unrenderable state --
# matches the configurator's "starts as one default tab" convention (AER-173
# design doc, makerplane-data#38 section 4a).
_EMPTY_TAB_LABEL = "Tab 1"
_EMPTY_TAB_LAYOUT = {"rows": 1, "columns": 1}

# tab_position -> QTabBar.Shape. West/East also rotate the tab labels
# vertically -- a side effect of the shape, not something set separately.
_TAB_BAR_SHAPE = {
    "top": QTabBar.Shape.RoundedNorth,
    "bottom": QTabBar.Shape.RoundedSouth,
    "left": QTabBar.Shape.RoundedWest,
    "right": QTabBar.Shape.RoundedEast,
}


class TabSection(QWidget):
    """Container instrument: an ordered set of named tabs, each a nested
    ``Screen`` built from its own ``layout``/``instruments`` config, laid out
    against this widget's own box rather than the enclosing screen's."""

    def __init__(self, screen, tabs=None, default_tab=0, font_family=None):
        super().__init__(screen)
        # Deferred import: screenbuilder.py imports screenbuilder_factory,
        # which imports this module to bind build_tab_section -- importing
        # Screen at module load time would be circular.
        from pyefis.screens.screenbuilder import Screen as ScreenBuilder

        self._font_family = font_family
        self._fg_color = None
        self._bg_color = None
        self.tab_position = "top"
        self._pages = []
        self.tab_bar = QTabBar(self)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(True)
        if font_family:
            font = QFont(self.tab_bar.font())
            font.setFamily(font_family)
            self.tab_bar.setFont(font)
        self.stack = QStackedWidget(self)

        config_parent = screen.parent
        for tab in (tabs or []) or [
                {"label": _EMPTY_TAB_LABEL, "layout": _EMPTY_TAB_LAYOUT,
                 "instruments": []}]:
            label = tab.get("label") or f"Tab {len(self._pages) + 1}"
            self.tab_bar.addTab(label)
            page_config = {
                "layout": tab.get("layout", _EMPTY_TAB_LAYOUT),
                "instruments": tab.get("instruments", []) or [],
            }
            page = ScreenBuilder(parent=config_parent, config=page_config)
            self.stack.addWidget(page)  # reparents page's Qt widget to stack
            self._pages.append(page)

        self.default_tab = default_tab
        self._show_tab(default_tab if 0 <= default_tab < len(self._pages) else 0)
        self.tab_bar.currentChanged.connect(self._show_tab)

    def _show_tab(self, index):
        if not (0 <= index < len(self._pages)):
            return
        self.tab_bar.blockSignals(True)
        self.tab_bar.setCurrentIndex(index)
        self.tab_bar.blockSignals(False)
        self.stack.setCurrentIndex(index)

    @property
    def fg_color(self):
        return self._fg_color

    @fg_color.setter
    def fg_color(self, value):
        self._fg_color = value
        self._apply_tab_bar_style()

    @property
    def bg_color(self):
        return self._bg_color

    @bg_color.setter
    def bg_color(self, value):
        self._bg_color = value
        self._apply_tab_bar_style()

    def _apply_tab_bar_style(self):
        """Panel-designer override on top of the inherited (screenbuilder.py
        central-palette) legibility floor. Unset (None, the default) means
        no override -- the tab bar keeps reading the inherited palette."""
        rules = []
        if self._fg_color:
            rules.append(f"color: {self._fg_color};")
        if self._bg_color:
            rules.append(f"background: {self._bg_color};")
        self.tab_bar.setStyleSheet(
            "QTabBar::tab { %s }" % " ".join(rules) if rules else ""
        )

    def _layout_pages(self):
        """Position the tab bar + content area against THIS widget's own
        box, on whichever edge ``tab_position`` names, then size every page
        (current tab or not) to that content area -- the coordinate-space
        recursion pyEfis#131 calls out as the real lift: a tab's instruments
        are laid out against the container's box, never the enclosing
        screen's.

        West/East bars are sized off ``sizeHint().width()`` -- rotating the
        bar to a side shape rotates the tab labels too, but Qt keeps
        reporting the bar's "thickness" (the dimension we need to reserve)
        on the width axis of its sizeHint, not the height."""
        tab_position = self.tab_position if self.tab_position in _TAB_BAR_SHAPE \
            else "top"
        self.tab_bar.setShape(_TAB_BAR_SHAPE[tab_position])
        if tab_position in ("top", "bottom"):
            bar_size = self.tab_bar.sizeHint().height()
            content_w = self.width()
            content_h = max(0, self.height() - bar_size)
            if tab_position == "top":
                bar_geom = (0, 0, self.width(), bar_size)
                stack_geom = (0, bar_size, content_w, content_h)
            else:
                bar_geom = (0, content_h, self.width(), bar_size)
                stack_geom = (0, 0, content_w, content_h)
        else:
            bar_size = self.tab_bar.sizeHint().width()
            content_w = max(0, self.width() - bar_size)
            content_h = self.height()
            if tab_position == "left":
                bar_geom = (0, 0, bar_size, self.height())
                stack_geom = (bar_size, 0, content_w, content_h)
            else:
                bar_geom = (content_w, 0, bar_size, self.height())
                stack_geom = (0, 0, content_w, content_h)
        self.tab_bar.setGeometry(*bar_geom)
        self.stack.setGeometry(*stack_geom)
        for page in self._pages:
            page.setGeometry(0, 0, content_w, content_h)

    def initScreen(self):
        """Called by the enclosing Screen's grid_layout(), right after this
        widget is moved/resized to its final geometry -- the same "build it
        now, don't wait for first show" hook gui.Main uses for inactive
        top-level screens (screenbuilder.py move_resize_inst caller). Needed
        because .resize() does not reliably deliver a synchronous
        resizeEvent to a widget with no shown top-level window yet, and each
        page is itself a Screen that only builds its instruments from its
        own resizeEvent/initScreen()."""
        self._layout_pages()
        for page in self._pages:
            page.initScreen()

    def resizeEvent(self, event):
        self._layout_pages()
        super().resizeEvent(event)

    def closeEvent(self, event):
        for page in self._pages:
            try:
                page.close()
            except Exception:
                logger.exception("tab_section: error closing a tab page")
        if event is not None:
            super().closeEvent(event)
