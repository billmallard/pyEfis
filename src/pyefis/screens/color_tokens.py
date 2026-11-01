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

"""Semantic colour tokens -- the theme layer's colour vocabulary.

The ONE place the token vocabulary is registered (style contract section 6).
A colour option's value may be a token name or a literal: ``fg_color:
ink.primary`` and ``fg_color: "#ffffff"`` are both legal, and tokens are an
additional legal value, never a restriction.

Resolution order, lowest to highest (style contract section 7)::

    5. Prop default in REGISTRY
    4. theme token value   (styles: colors: <style> in preferences)
    3. preferences  styles: <TYPE>: <style>
    2. preferences  gauges: <ID>  /  gauges: <ID>: styles: <style>
    1. instance option in the screen YAML

    token resolution happens LAST, on whatever value won

Level 4 only fills a colour prop the cascade left unset, and only when the
active theme actually defines that prop's token -- with no ``colors:`` block a
widget keeps exactly the default it has always had. Each token's built-in value
is the current default of the props mapped to it, so introducing the tokens
moves nothing on screen.

``nav.*`` and ``state.*`` are theme-immutable (Tier 1): a theme changes how the
panel feels, never what a colour means. A ``colors:`` block that redefines one
is ignored with a warning. A builder may still override the prop itself per
widget -- it is their airplane.

This module is Qt-free so ``instrument_spec`` can validate against it.
"""

import logging

log = logging.getLogger(__name__)

# name -> (built-in value, description). A value of None means no shipped prop
# reads the token yet, so there is no current default to adopt; a theme may
# still define it (immutable tokens excepted) and an option naming it is left to
# the widget's default until it has a value.
TOKENS = {
    "surface.base":   ("#000000", "panel ground"),
    "surface.raised": ("#101418", "readout boxes, plates, buttons"),
    "ink.primary":    ("#ffffff", "primary data values"),
    "ink.secondary":  ("#ffffff", "labels, units, prefixes"),
    "ink.muted":      ("#aaaaaa", "inactive, section headers, disabled"),
    "line.border":    ("#ffffff", "borders and frames"),
    "line.major":     (None, "cardinal / 30 degree ticks"),
    "line.minor":     (None, "10 degree ticks"),
    "line.fine":      (None, "5 degree ticks"),
    "accent":         ("#00ffff", "interactive / selected / focused"),
    "state.valid":    ("#00ff00", "received, complete, in-range"),
    "state.caution":  ("#ffaa00", "attention"),
    "state.warning":  (None, "exceeded, failed"),
    "nav.course":     ("#ff00ff", "active course and track"),
    "nav.reference":  ("#00ffff", "bugs, selected values"),
    "nav.ownship":    ("#ffff00", "own-ship symbology"),
    "map.road":       ("#c0c0c0", "roads and highways"),
    "map.water":      ("#4a6d8c", "water bodies and rivers"),
    "map.terrain":    (None, "terrain base"),
}

# Token groups a theme may not redefine (style contract sections 4 and 8).
IMMUTABLE_GROUPS = ("nav", "state")

# The preferences key under ``styles:`` that holds per-style token values,
# alongside the per-type option blocks.
COLORS_KEY = "colors"


def is_token(value):
    return isinstance(value, str) and value in TOKENS


def is_immutable(token):
    return token.split(".", 1)[0] in IMMUTABLE_GROUPS


def default_value(token):
    return TOKENS[token][0]


def _is_color_option(name, color_props):
    # Declared colour props of a migrated type, plus the naming convention for
    # types not yet in the registry.
    return name in color_props or name.endswith("color") or name.endswith("colour")


def theme_colors(preferences):
    """Token values defined by the active theme: every enabled style's
    ``styles: colors: <style>`` block merged in ``style:`` order, later styles
    winning -- the same combination rule the per-type blocks follow. Unknown and
    theme-immutable tokens are dropped with a warning. Never raises."""
    colors = {}
    if not isinstance(preferences, dict):
        return colors
    styles = preferences.get("styles") or {}
    blocks = styles.get(COLORS_KEY) if isinstance(styles, dict) else None
    if not isinstance(blocks, dict):
        return colors
    for style, enabled in (preferences.get("style") or {}).items():
        if not enabled:
            continue
        block = blocks.get(style)
        if not isinstance(block, dict):
            continue
        for token, value in block.items():
            if token not in TOKENS:
                log.warning("theme '%s': unknown colour token '%s' ignored",
                            style, token)
            elif is_immutable(token):
                log.warning("theme '%s': colour token '%s' is theme-immutable; "
                            "ignored", style, token)
            elif value is not None:
                colors[token] = value
    return colors


def resolve(value, colors):
    """Resolve one option value. A token name becomes the theme's value, else
    the built-in value; anything else (a literal, a Qt colour name) is returned
    unchanged. Returns None for a token with no value anywhere."""
    if not is_token(value):
        return value
    if value in colors and not is_immutable(value):
        return colors[value]
    return default_value(value)


def apply_theme_colors(config, preferences, color_props=None):
    """Apply level 4 of the resolution order and then token resolution to one
    instrument config, after the preferences cascade has picked its options.

    ``color_props`` maps each declared colour prop of the instrument's type to
    its token (or "" when unmapped); see ``prop_tokens``."""
    color_props = color_props or {}
    colors = theme_colors(preferences)
    options = dict(config.get("options") or {})
    changed = False

    # Level 4: the active theme supplies a mapped prop nothing else set. These
    # go FIRST, so they are applied before any option whose setter repaints
    # from the colours already set (value_text's setDbkey -> setColors).
    filled = {name: token for name, token in color_props.items()
              if token and name not in options and token in colors}
    if filled:
        options = filled | options
        changed = True

    # Token resolution, last, on whatever value won.
    for name in list(options):
        value = options[name]
        if not is_token(value) or not _is_color_option(name, color_props):
            continue
        resolved = resolve(value, colors)
        if resolved is None:
            log.warning("instrument '%s': option '%s' names colour token '%s', "
                        "which has no value yet; using the widget default",
                        config.get("type"), name, value)
            del options[name]
        else:
            options[name] = resolved
        changed = True

    if changed:
        config["options"] = options
    return config


def prop_tokens(spec):
    """{colour prop name: token} for one InstrumentSpec (None -> {})."""
    if spec is None:
        return {}
    return {p.name: p.token for p in spec.properties if p.kind == "color"}
