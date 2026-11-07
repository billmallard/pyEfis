#!/usr/bin/env python3
"""Generate the option tables for the wiki's instrument reference pages.

The tables come straight from pyEFIS's instrument registry
(src/pyefis/screens/screenbuilder_factory.py REGISTRY), the same records the
configurator's palette and Properties panel are built from. So a table here is
the code, not a transcription of it.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 docs/images/reference/gen_reference.py --update docs/wiki

rewrites, in every page under docs/wiki, the text between
``<!-- generated:<type> -->`` and ``<!-- /generated -->`` with that type's
block, and between ``<!-- generated:index -->`` and ``<!-- /generated -->`` with
the summary table. Everything outside the markers is hand-written and left
alone. ``gen_reference.py OUTDIR`` instead writes OUTDIR/<type>.md and
OUTDIR/_index.md, for a look before updating.
"""
import os
import re
import sys

from pyefis.screens import screenbuilder_factory as factory

# Internal tracking references in help text, dropped from the public manual.
_REFS = [
    (re.compile(r"\s*\(v1, see pyEfis#\d+[^)]*\)"), ""),
    (re.compile(r"\s*\(#\d+\)"), ""),
    (re.compile(r"\((?:FP|PA)\d+[a-z]?;\s*"), "("),
    (re.compile(r"\bprocedures-conus\.pack\b"), "the procedures pack"),
    (re.compile(r"\.\s*Phase 1 authors this by hand; later the configurator builds it per-aircraft"), ""),
]

# Where each instrument is explained for the pilot, when it has a page.
OPERATION = {
    "virtual_vfr": "Attitude-and-Synthetic-Vision",
    "atitude_indicator": "Attitude-and-Synthetic-Vision",
    "airspeed_tape": "Airspeed-Altitude-and-Vertical-Speed",
    "altimeter_tape": "Airspeed-Altitude-and-Vertical-Speed",
    "altimeter_trend_tape": "Airspeed-Altitude-and-Vertical-Speed",
    "wind_display": "The-Panel-at-a-Glance#wind",
    "horizontal_situation_indicator": "The-HSI",
    "moving_map": "Moving-Map",
    "flight_plan": "Flight-Plan",
    "nav_status": "Flight-Plan#the-nav-status-line",
    "arc_gauge": "Engine-Monitoring",
    "vertical_bar_gauge": "Engine-Monitoring",
    "horizontal_bar_gauge": "Engine-Monitoring",
    "numeric_display": "Engine-Monitoring",
    "data_status": "Data-Status-Updates-and-Notices",
    "data_annunciation": "Data-Status-Updates-and-Notices#the-data-flag",
    "about": "Data-Status-Updates-and-Notices#the-about-screen",
    "tab_section": "The-Panel-at-a-Glance#the-tab-column",
}


TITLES = {
    "Attitude-and-Synthetic-Vision": "Attitude and Synthetic Vision",
    "Airspeed-Altitude-and-Vertical-Speed": "Airspeed, Altitude and Vertical Speed",
    "The-Panel-at-a-Glance": "The Panel at a Glance",
    "The-HSI": "The HSI",
    "Moving-Map": "Moving Map",
    "Flight-Plan": "Flight Plan",
    "Engine-Monitoring": "Engine Monitoring",
    "Data-Status-Updates-and-Notices": "Data Status, Updates and Notices",
}


def clean(text):
    text = (text or "").strip()
    for rx, rep in _REFS:
        text = rx.sub(rep, text)
    return text.replace("|", "\\|").replace("\n", " ")


def fmt_default(prop):
    d = prop.default
    if d is None:
        return "unset"
    if isinstance(d, bool):
        return "on" if d else "off"
    if d == "":
        return "empty"
    if isinstance(d, float) and d.is_integer():
        d = int(d)
    if isinstance(d, float):
        d = round(d, 3)
    return "`%s`" % (d,)


def fmt_values(prop):
    if prop.enum:
        return ", ".join("`%s`" % e for e in prop.enum)
    parts = []
    if prop.minimum is not None or prop.maximum is not None:
        lo = "" if prop.minimum is None else _num(prop.minimum)
        hi = "" if prop.maximum is None else _num(prop.maximum)
        parts.append("%s to %s" % (lo or "...", hi or "..."))
    if prop.step is not None:
        parts.append("step %s" % _num(prop.step))
    kind = {"boolean": "on / off", "color": "colour", "fixkey": "FIX key"}.get(prop.kind)
    if not parts and kind:
        parts.append(kind)
    return ", ".join(parts)


def _num(v):
    return str(int(v)) if float(v).is_integer() else str(round(float(v), 3))


def block(spec):
    out = []
    facts = ["**%s**" % spec.label, "palette category `%s`" % spec.category]
    if spec.hidden:
        facts.append("hidden from the palette, still loads in existing panels")
    out.append(" · ".join(facts) + "\n")
    page = OPERATION.get(spec.type)
    if page:
        name = TITLES[page.split("#")[0]]
        out.append("How it reads and flies: [%s](%s).\n" % (name, page))
    if spec.dbkeys:
        out.append("FIX keys it reads by default: %s.\n"
                   % ", ".join("`%s`" % k for k in spec.dbkeys))
    if spec.properties:
        out.append("| Option | Configurator label | Default | Values | What it does |")
        out.append("|---|---|---|---|---|")
        for p in spec.properties:
            out.append("| `%s` | %s | %s | %s | %s |" % (
                p.name, clean(p.label), fmt_default(p), fmt_values(p), clean(p.help)))
        out.append("")
    else:
        out.append("No options in the configurator beyond the ones every instrument takes.\n")
    if spec.fix_values:
        out.append("Values it reads from the FIX item, set in fix-gateway (the aircraft "
                   "parameters), not on the panel:\n")
        out.append("| Value | From | Meaning |")
        out.append("|---|---|---|")
        for v in spec.fix_values:
            meaning = clean(v.label) + (" (%s)" % v.units if v.units else "")
            out.append("| `%s` | %s | %s |" % (v.name, v.source, meaning))
        out.append("")
    for c in spec.containers:
        out.append("Holds `%s:` (%s): %s\n" % (c.name, clean(c.label), clean(c.help)))
    return "\n".join(out).rstrip() + "\n"


# Which reference page carries each type.
PAGES = {
    "Widgets-Flight-Instruments": "Flight Instruments",
    "Widgets-Attitude-and-SVS": "Attitude & SVS",
    "Widgets-Navigation": "Navigation",
    "Widgets-Engine-Gauges": "Engine & Data Gauges",
    "Widgets-Text-and-Interactive": "Text & Interactive",
    "Widgets-System": "System & Containers",
}
_MARK = re.compile(r"(<!-- generated:([a-z_]+) -->\n).*?(<!-- /generated -->)", re.S)


def page_of(wiki):
    """type -> reference page, from the markers in the pages themselves."""
    where = {}
    for page in PAGES:
        path = os.path.join(wiki, page + ".md")
        if os.path.exists(path):
            for m in _MARK.finditer(open(path).read()):
                if m.group(2) != "index":
                    where[m.group(2)] = page
    return where


def index(where=None):
    where = where or {}
    rows = ["| Type | Name | Category | FIX keys read by default | Reference |",
            "|---|---|---|---|---|"]
    for t, s in sorted(factory.REGISTRY.items()):
        name = s.label + (" (hidden)" if s.hidden else "")
        page = where.get(t)
        ref = "[%s](%s#%s)" % (PAGES[page], page, t) if page else "--"
        rows.append("| `%s` | %s | %s | %s | %s |" % (
            t, name, s.category, ", ".join("`%s`" % k for k in s.dbkeys) or "--", ref))
    return "\n".join(rows) + "\n"


def update(wiki):
    where = page_of(wiki)
    missing = sorted(set(factory.REGISTRY) - set(where))
    if missing:
        print("not on any reference page: " + ", ".join(missing))
    blocks = {t: block(s) for t, s in factory.REGISTRY.items()}
    blocks["index"] = index(where)
    for name in os.listdir(wiki):
        if not name.endswith(".md"):
            continue
        path = os.path.join(wiki, name)
        text = open(path).read()
        new = _MARK.sub(lambda m: m.group(1) + "\n" + blocks.get(m.group(2), "") + "\n" + m.group(3), text)
        if new != text:
            open(path, "w").write(new)
            print("updated " + name)


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    for t, s in factory.REGISTRY.items():
        with open(os.path.join(outdir, t + ".md"), "w") as fh:
            fh.write(block(s))
    with open(os.path.join(outdir, "_index.md"), "w") as fh:
        fh.write(index())
    print("%d types" % len(factory.REGISTRY))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--update":
        update(sys.argv[2])
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "reference_out")
