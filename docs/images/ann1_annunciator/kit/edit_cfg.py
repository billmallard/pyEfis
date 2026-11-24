"""AER-6347: point a scratch copy of the live pyEfis config at the private
gateway and add the 2x3 annunciator block to the PFD (managed.yaml)."""
import sys, yaml, re
pcfg = sys.argv[1]
p = f"{pcfg}/main/default.yaml"
s = open(p).read()
s = re.sub(r"FixPort: *3490", "FixPort: 3497", s)
open(p, "w").write(s)
p = f"{pcfg}/screens/managed.yaml"
d = yaml.safe_load(open(p))
d["PFD"]["instruments"].append({
    "type": "annunciator", "row": 70, "column": 94,
    "span": {"rows": 16, "columns": 35},
    "options": {
        "rows": 2, "cols": 3, "font_family": "B612",
        "tiles": [
            {"label": "AP", "key": "APENG", "level": "status",
             "flash_on_change": 5},
            {"label": "YD", "key": "YDENG", "level": "status"},
            {"label": "ALT CAP", "key": "APALTCAP", "level": "advisory"},
            {"label": "NAV", "key": "NAVSRC", "level": "info",
             "enum": {0: "VLOC1", 1: "VLOC2", 2: "GPS"}},
            {"label": "ALT ALERT", "key": "ALTSEL", "flag": "annunciate",
             "level": "caution"},
            {"label": "VS HIGH", "key": "VS", "when": "VS gt 1500",
             "level": "warning"},
        ],
    },
})
yaml.safe_dump(d, open(p, "w"), sort_keys=False)
print("edited", p)
