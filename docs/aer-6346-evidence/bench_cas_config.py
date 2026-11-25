"""AER-6346: CAS3 bench config, layout-agnostic. Backs up, then enables the
fix-gateway cas plugin (preferences.yaml.custom), adds a CAS tab after the
named radio tab plus a marker on the boot screen, and a marker on every other
listed screen. Each file is re-parsed before it is written.
usage: PCFG FCFG BOOT_SCREEN RADIO_LABEL OTHER1,OTHER2,..."""
import os, re, shutil, sys, time
import yaml

PCFG, FCFG, BOOT, RADIO = sys.argv[1:5]
OTHERS = [x for x in sys.argv[5].split(",") if x]
BK = os.path.expanduser("~/bench-scratch/aer6346-config-backup-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
os.makedirs(BK)
print("backup:", BK)


def backup(path, tag):
    if os.path.exists(path):
        shutil.copy2(path, os.path.join(BK, tag + "__" + os.path.basename(path)))


def write(path, text):
    yaml.safe_load(text)
    os.remove(path)
    with open(path, "w") as f:
        f.write(text)


def indent(block, n):
    return "".join((" " * n + l if l.strip() else l) + "\n" for l in block.strip("\n").split("\n"))


def add_instrument(s, block):
    """Insert *block* (written at indent 0, starting '- type:') as the last
    item of the screen's instruments list, at that list's indentation."""
    m = re.search(r"^( *)instruments:\n( *)- type:", s, re.M)
    if not m:
        raise ValueError("no instruments list")
    ind = len(m.group(2))
    base = len(m.group(1))
    # a key at the screen's own level after instruments (include:, ...) ends the list
    tail = re.search(r"^ {%d}[a-z_]+:" % base, s[m.end():], re.M)
    at = m.end() + tail.start() if tail else len(s.rstrip("\n")) + 1
    s = s if s.endswith("\n") else s + "\n"
    return s[:at] + indent(block, ind) + s[at:]


MARKER = """- type: cas_marker
  row: {row}
  column: {col}
  span:
    rows: 6
    columns: {cols}"""
COMMENT = "# AER-6346 CAS3 bench: crew alerting marker (highest active level; touch for the full list).\n"

# 1. fix-gateway
p = os.path.join(FCFG, "preferences.yaml.custom")
backup(p, "fixgw")
s = open(p).read()
if "CAS_CONFIG" not in s:
    if "includes:\n" not in s:
        s = "includes:\n" + s
    if "enabled:\n" not in s:
        s = s.rstrip("\n") + "\nenabled:\n"
    s = s.replace("includes:\n", "includes:\n  # AER-6346 CAS3 bench: crew alerting plugin.\n  CAS_CONFIG: connections/cas.yaml\n", 1)
    s = s.replace("enabled:\n", "enabled:\n  # AER-6346 CAS3 bench: crew alerting on.\n  CAS: true\n", 1)
    write(p, s)
    print("fixgw: cas enabled")
else:
    print("fixgw: cas already configured")

# 2. boot screen: CAS tab after the radio tab, and a marker
p = os.path.join(PCFG, BOOT)
backup(p, "pyefis")
s = open(p).read()
if "cas_window" not in s:
    m = re.search(r"^( *)- label: %s\n" % re.escape(RADIO), s, re.M)
    ti = len(m.group(1))
    # the radio tab ends at the next line indented <= its dash, or EOF
    nxt = re.search(r"^ {0,%d}\S" % ti, s[m.end():], re.M)
    at = m.end() + nxt.start() if nxt else len(s.rstrip("\n")) + 1
    s = s if s.endswith("\n") else s + "\n"
    tab = """- label: CAS
  layout:
    rows: 110
    columns: 200
  instruments:
  - type: cas_window
    row: 2
    column: 2
    span:
      rows: 104
      columns: 196
    options:
      lines: 10"""
    s = s[:at] + indent(tab, ti) + s[at:]
    s = add_instrument(s, MARKER.format(row=0, col=104, cols=25))
    write(p, s)
    d = yaml.safe_load(s)
    (name, scr), = d.items()
    tabs = [t["label"] for i in scr["instruments"] if i["type"] == "tab_section" for t in i["tabs"]]
    print("boot screen", name, "tabs:", tabs, "| marker:", any(i["type"] == "cas_marker" for i in scr["instruments"]))

# 3. other screens
for rel in OTHERS:
    p = os.path.join(PCFG, rel)
    if not os.path.exists(p):
        print("skip (absent):", rel); continue
    s = open(p).read()
    if "cas_marker" in s:
        print("has marker:", rel); continue
    backup(p, "pyefis")
    try:
        t = add_instrument(s, MARKER.format(row=1, col=38, cols=20))
        write(p, t)
        d = yaml.safe_load(t)
        (name, scr), = d.items()
        print("marker added:", rel, any(i["type"] == "cas_marker" for i in scr["instruments"]))
    except Exception as e:
        print("FAILED", rel, e)
print("done")
