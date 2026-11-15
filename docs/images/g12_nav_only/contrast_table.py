#!/usr/bin/env python3
"""G12 contrast bound: WCAG 2.x contrast of every retained map layer against
its background, read from the palette tables in the source so it cannot drift.

A computed ratio is a BOUND, not the device check (#135). Alpha colours are
composited over the background they sit on before the ratio is taken.

    PYTHONPATH=src python docs/images/g12_nav_only/contrast_table.py
"""
from pyefis.instruments.map import layers as L

STD, NAV = L.STANDARD_PALETTE, L.NAV_ONLY_PALETTE


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb):
    r, g, b = rgb[:3]
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _hex(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def _over(fg, bg):
    a = (fg[3] if len(fg) > 3 else 255) / 255.0
    return tuple(round(fg[i] * a + bg[i] * (1 - a)) for i in range(3))


def ratio(fg, bg):
    f, b = _lum(_over(fg, bg)), _lum(bg)
    return (max(f, b) + 0.05) / (min(f, b) + 0.05)


# (layer, element, standard colour, nav_only colour, floor, also-over-water)
# floor: 3.0 = graphical symbol / reference line, 4.5 = text.
ROWS = [
    ("airports", "symbol + runway edge", STD["airport"], NAV["airport"], 3.0, True),
    ("airports", "ident label", (255, 255, 255, 230), (255, 255, 255, 230), 4.5, True),
    ("navaids", "VOR/NDB symbol", STD["navaid"], NAV["navaid"], 3.0, True),
    ("navaids", "ident + freq label", (220, 230, 255, 255), (220, 230, 255, 255), 4.5, True),
    ("fixes", "triangle", STD["fix"], NAV["fix"], 3.0, True),
    ("fixes", "ident label", (200, 210, 235, 220), (200, 210, 235, 220), 4.5, True),
    ("airways", "segment line", STD["airway"], NAV["airway"], 3.0, True),
    ("airways", "ident label", (150, 180, 240, 255), (150, 180, 240, 255), 4.5, True),
    ("flight_plan", "active leg", (255, 0, 255, 255), (255, 0, 255, 255), 3.0, True),
    ("flight_plan", "future leg / label", (255, 255, 255, 255), (255, 255, 255, 255), 4.5, True),
    ("flight_plan", "past leg", STD["route_past"], NAV["route_past"], 3.0, True),
    ("ownship", "symbol (symbol_color default)", (255, 255, 0, 255), (255, 255, 0, 255), 3.0, True),
    ("range_rings", "ring", STD["range_ring"], NAV["range_ring"], 3.0, False),
    ("range_rings", "distance label", STD["range_ring_label"], NAV["range_ring_label"], 4.5, False),
    ("roads", "interstate (tier 0)", _hex(STD["road_default"]), _hex(NAV["road_default"]), 3.0, False),
    ("roads", "arterial (tier 2, alpha 170)", _hex(STD["road_default"])[:3] + (170,),
     _hex(NAV["road_default"])[:3] + (170,), None, False),
    ("rivers", "river (tier 0)", _hex(STD["river_default"]), _hex(NAV["river_default"]), 3.0, False),
    ("water", "fill (area)", STD["water"], NAV["water"], None, False),
]


def main():
    sbg, nbg, nw = STD["background"], NAV["background"], NAV["water"]
    print("standard background %s; nav_only background %s, water fill %s"
          % (sbg[:3], nbg[:3], nw[:3]))
    print()
    print("| Layer | Element | Floor | standard on its bg %s | nav_only colour | "
          "nav_only on black | nav_only on water | Meets floor |" % (sbg[:3],))
    print("|---|---|---|---|---|---|---|---|")
    for layer, el, s, n, floor, water in ROWS:
        rs, rn = ratio(s, sbg), ratio(n, nbg)
        rw = ratio(n, nw) if water else None
        ok = "-" if floor is None else (
            "yes" if rn >= floor and (rw is None or rw >= floor) else "NO")
        print("| %s | %s | %s | %.2f | %s | %.2f | %s | %s |" % (
            layer, el, "-" if floor is None else "%.1f:1" % floor, rs,
            "rgb%s%s" % (tuple(n[:3]), "" if n[3] == 255 else " a%d" % n[3]),
            rn, "-" if rw is None else "%.2f" % rw, ok))


if __name__ == "__main__":
    main()
