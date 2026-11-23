#  SPDX-License-Identifier: GPL-2.0-or-later
"""Score the AER-6288 live frames: does the strip show exactly what the bus
reports, in every frame?  (README.md beside this file.)

    QT_QPA_PLATFORM=offscreen python3 score.py <run dir> [<strip_geometry.json>]

Run from a pyEfis checkout (it imports the widget and tests/mock_db). Reads
<run>/bus.jsonl (every update the private gateway sent, with its flags),
<run>/frames.jsonl and <run>/frames/*.png. Writes <run>/score.jsonl,
<run>/sheet.png and <run>/glass.png.

1. **Expected**, from the bus alone. The bus is replayed in time order up to
   each grab. The strip text follows the spec (ap_annunciator_widget_spec.md
   sections 2-3), written out here rather than taken from the widget's model:
   the eight state keys are one reading; any of them old, bad or failed is
   NO AP DATA (amber if APENG was True at the last fresh reading, grey if
   not; nothing before the first fresh reading). Otherwise AP (red while
   APDISC), YD, APLAT, APLATARM, then ALT CAP while APALTCAP, else APVERT
   with its target (VS VSSEL, IAS IASSEL, ALT APALTREF) when the target
   key's flags are clean, then APVERTARM.
2. **Seen**, from the pixels, one slot at a time (AP, YD, lateral active,
   lateral armed, vertical active, vertical armed). Each slot of the frame is
   compared with every plausible thing that slot could show, painted by the
   real ModeAnnunciator at the strip's size: the expected text, every mode
   name the strip knows, the expected number's neighbours (VS +-100/200/500
   and the sign flipped, IAS +-1/2/5/10, ALT +-10/20/100/200/500/1000), each
   in both colours (active green, armed white), each flash look (plain, boxed
   with the text on, boxed with it off), and the empty slot. Pixels are
   reduced to ink classes (green, white, red, grey, amber); the best
   class-labelled overlap is what the slot shows. Expecting only the states
   the bus visited is not enough: the glass could show a state outside that
   set (a mutation of the bus log showed it), hence the open lexicon.
   The whole strip is also compared with NO AP DATA in both colours, so a
   fresh reading must beat both, and NO AP DATA must beat the last fresh
   reading.
3. **Verdict:** `match` when every slot shows the expected state at the grab
   (a slot in a flash's off phase shows the box and no text; it counts when
   the expected mode's box is the best look to within HIDDEN_TOL, and the
   count of such frames is reported),
   `edge` when every slot shows a state the bus held from LAG_S before the
   grab to the end of the grab (a frame on a state change: the display had
   not repainted yet, or ffmpeg grabbed after the change), else `MISMATCH`.
"""

import bisect
import collections
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.getcwd()
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

import tests.mock_db.client  # noqa: E402
import tests.mock_db.scheduler  # noqa: E402
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtCore import Qt, QRectF  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import pyavtools.fix as fix  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
from tests.instruments.autopilot.conftest import AFC1_KEYS  # noqa: E402
for key, dtype, lo, hi, tol in AFC1_KEYS:
    fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")

from pyefis.instruments.autopilot import fma  # noqa: E402

RUN = sys.argv[1]
GEO = json.load(open(sys.argv[2] if len(sys.argv) > 2 else
                     os.path.join(RUN, "..", "strip_geometry.json")))
X0, Y0 = int(round(GEO["x"])), int(round(GEO["y"]))
W, H = int(round(GEO["render_width"])), int(round(GEO["render_height"]))

STATE = ("APENG", "YDENG", "APLAT", "APLATARM", "APVERT", "APVERTARM",
         "APALTCAP", "APDISC")
TARGET = {"VS": "VSSEL", "IAS": "IASSEL", "ALT": "APALTREF"}
LAG_S = 1.0
#: How close the expected mode's boxed, text-off look must come to the best
#: look for the slot to read as "flash off phase, text hidden".
HIDDEN_TOL = 0.03
#: The strip's left-to-right order (ap_position left, the default).
ORDER = ("ap", "yd", "lat", "lat_arm", "vert", "vert_arm")
#: The strip paints its background only when it shows something; with nothing
#: to show, the attitude display shows through (sky, or the grey of a failed
#: attitude). A median luminance of the strip area above this is a blank strip;
#: the strip's own 75 % black background keeps it far below.
BLANK_LUMA = 70


# -- 1. expected, from the bus ------------------------------------------------
def clean(flags):
    return flags is not None and flags[1:4] == "000"      # old, bad, fail


def truthy(v):
    return v == "True"


def modes(v):
    return [m.strip().upper() for m in (v or "").split(",") if m.strip()]


def num(v):
    return int(round(float(v)))


class Replay:
    """Bus state at a time, with the strip's two latches (seen live, engaged
    at the last fresh reading)."""

    def __init__(self, rows):
        self.rows = rows
        self.i = 0
        self.cur = {}
        self.seen = False
        self.engaged = False

    def advance(self, t):
        while self.i < len(self.rows) and self.rows[self.i]["t"] <= t:
            r = self.rows[self.i]
            self.cur[r["k"]] = (r["v"], r["f"])
            self.i += 1
            if self.fresh():
                self.seen = True
                self.engaged = truthy(self.cur["APENG"][0])

    def fresh(self):
        return all(k in self.cur and clean(self.cur[k][1]) for k in STATE)

    def expected(self):
        """A tuple of (slot, text, role), sorted by slot order."""
        if not self.fresh():
            if not self.seen:
                return ()
            role = fma.ROLE_NODATA_CAUTION if self.engaged else fma.ROLE_NODATA
            return (("nodata", fma.NO_DATA_TEXT, role),)
        v = {k: self.cur[k][0] for k in STATE}
        out = []
        if truthy(v["APDISC"]):
            out.append(("ap", "AP", fma.ROLE_WARNING))
        elif truthy(v["APENG"]):
            out.append(("ap", "AP", fma.ROLE_ACTIVE))
        if truthy(v["YDENG"]):
            out.append(("yd", "YD", fma.ROLE_ACTIVE))
        lat = (v["APLAT"] or "").strip().upper()
        if lat:
            out.append(("lat", lat, fma.ROLE_ACTIVE))
        if modes(v["APLATARM"]):
            out.append(("lat_arm", " ".join(modes(v["APLATARM"])), fma.ROLE_ARMED))
        vert = (v["APVERT"] or "").strip().upper()
        if truthy(v["APALTCAP"]):
            out.append(("vert", "ALT CAP", fma.ROLE_ACTIVE))
        elif vert:
            text = vert
            tk = TARGET.get(vert)
            if tk and tk in self.cur and clean(self.cur[tk][1]):
                n = num(self.cur[tk][0])
                text = {"VS": "VS %+d" % n if n else "VS 0",
                        "IAS": "IAS %d" % n, "ALT": "ALT %d" % n}[vert]
            out.append(("vert", text, fma.ROLE_ACTIVE))
        if modes(v["APVERTARM"]):
            out.append(("vert_arm", " ".join(modes(v["APVERTARM"])), fma.ROLE_ARMED))
        return tuple(out)


def label(state):
    if not state:
        return "(blank)"
    d = {s: (t, r) for s, t, r in state}
    if "nodata" in d:
        return "%s (%s)" % (d["nodata"][0], d["nodata"][1])
    parts = []
    for s in ORDER:
        if s in d:
            t, r = d[s]
            parts.append("[%s]" % t if r == fma.ROLE_ARMED else
                         ("%s!" % t if r == fma.ROLE_WARNING else t))
    return " ".join(parts)


# -- 2. seen, from the pixels --------------------------------------------------
def to_array(img):
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    a = np.frombuffer(img.constBits().asstring(h * bpl), np.uint8)
    return a.reshape(h, bpl)[:, :w * 3].reshape(h, w, 3).astype(np.int16)


def ink(a):
    """0 none, 1 green, 2 white, 3 red, 4 grey, 5 amber."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    out = np.zeros(a.shape[:2], np.uint8)
    out[(g > 120) & (g - r > 60) & (g - b > 60)] = 1
    out[(mn > 170) & (mx - mn < 50)] = 2
    out[(r > 150) & (r - g > 90) & (r - b > 90)] = 3
    out[(mn > 85) & (mx < 175) & (mx - mn < 30)] = 4
    out[(r > 180) & (g > 110) & (g < 225) & (b < 90) & (r - g > 30)] = 5
    return out


class Fake:
    def __init__(self, cells, t):
        self._cells, self._t = cells, t

    def cells(self, now=None):
        return self._cells

    def clock(self):
        return self._t


widget = fma.ModeAnnunciator()
widget.resize(W, H)


def paint(cells, blink_on):
    widget.model = Fake(cells, 0.0 if blink_on else fma.BLINK_HALF_S)
    img = QImage(W, H, QImage.Format.Format_RGB888)
    img.fill(QColor("black"))
    p = QPainter(img)
    widget.render(p)
    p.end()
    return ink(to_array(img))


def overlap(o, t):
    either = (o > 0) | (t > 0)
    n = int(either.sum())
    return 1.0 if n == 0 else float(((o == t) & either).sum()) / n


RECTS = {k: (int(round(r.x())) + 4, int(round(r.x() + r.width())) - 4)
         for k, r in widget.slot_rects().items()}
LAT_MODES = ["HDG", "TRK", "ROL", "LVL", "GPS", "NAV", "VOR", "LOC", "BC", "APR"]
VERT_MODES = ["PIT", "ALT", "VS", "IAS", "ALT CAP", "LVL", "GS", "GP", "VNAV"]
ARM_LAT = ["GPS", "NAV", "VOR", "LOC", "APR", "BC", "LOC GPS"]
ARM_VERT = ["ALT", "GS", "GP", "VNAV", "VS", "ALT GS", "ALT GP", "ALT VNAV"]
DELTAS = {"VS": (100, -100, 200, -200, 500, -500),
          "IAS": (1, -1, 2, -2, 5, -5, 10, -10),
          "ALT": (10, -10, 20, -20, 100, -100, 200, -200, 500, -500, 1000, -1000)}
_cache = {}


def slot_look(slot, text, role, boxed, on):
    key = (slot, text, role, boxed, on)
    if key not in _cache:
        x0, x1 = RECTS[slot]
        if not text:
            _cache[key] = np.zeros((H, x1 - x0), np.uint8)
        else:
            full = paint({slot: fma.Cell(text, role, boxed=boxed, blink=boxed)}, on)
            _cache[key] = full[:, x0:x1]
    return _cache[key]


def slot_score(o, slot, text, role, hidden_out=None):
    """Best overlap of the frame's slot with any look of (text, role).
    With ``hidden_out``, also returns the score of the boxed, text-off look."""
    x0, x1 = RECTS[slot]
    crop = o[:, x0:x1]
    looks = [(False, True)]
    if text and (slot in ("lat", "vert") or role == fma.ROLE_WARNING):
        looks += [(True, True), (True, False)]
    if role == fma.ROLE_WARNING:
        looks = [(True, True), (True, False)]
    sc = {(b, on): overlap(crop, slot_look(slot, text, role, b, on))
          for b, on in looks}
    if hidden_out is not None:
        return max(sc.values()), sc.get((True, False), 0.0)
    return max(sc.values())


def neighbours(text):
    out = set()
    parts = text.split()
    if len(parts) == 2 and parts[0] in DELTAS:
        try:
            n = int(parts[1])
        except ValueError:
            return out
        for d in DELTAS[parts[0]]:
            m = n + d
            out.add("%s %s" % (parts[0], ("%+d" % m if m else "0")
                               if parts[0] == "VS" else "%d" % m))
        if parts[0] == "VS" and n:
            out.add("VS %+d" % -n)
    return out


def lexicon(slot, run_texts, expected_text):
    """Every (text, role) the slot is checked against."""
    act, arm, warn = fma.ROLE_ACTIVE, fma.ROLE_ARMED, fma.ROLE_WARNING
    if slot == "ap":
        return {("", None), ("AP", act), ("AP", warn), ("AP", arm)}
    if slot == "yd":
        return {("", None), ("YD", act), ("YD", arm)}
    names = set(run_texts.get(slot, ()))
    names.add(expected_text or "")
    names |= set({"lat": LAT_MODES, "vert": VERT_MODES,
                  "lat_arm": ARM_LAT, "vert_arm": ARM_VERT}[slot])
    for t in list(names):
        names |= neighbours(t)
    out = {("", None)}
    for t in names:
        if t:
            out.add((t, act))
            out.add((t, arm))
    return out


NODATA = [(fma.NO_DATA_TEXT, fma.ROLE_NODATA), (fma.NO_DATA_TEXT, fma.ROLE_NODATA_CAUTION)]
_nodata_looks = {r: paint({"nodata": fma.Cell(t, r)}, True) for t, r in NODATA}


def composite(state):
    """Whole-strip looks of a fresh state, plain and boxed (text on)."""
    base = {s: (t, r) for s, t, r in state}
    looks = []
    for boxed in (False, True):
        cells = {s: fma.Cell(t, r, boxed=(boxed and s in ("lat", "vert")) or
                             r == fma.ROLE_WARNING,
                             blink=(boxed and s in ("lat", "vert")) or
                             r == fma.ROLE_WARNING)
                 for s, (t, r) in base.items()}
        looks.append(paint(cells, True))
    return looks


def judge(o, state, run_texts, last_fresh):
    """(ok, detail) for one expected state against the frame's ink map."""
    if state and state[0][0] == "nodata":
        role = state[0][2]
        mine = overlap(o, _nodata_looks[role])
        rivals = [overlap(o, _nodata_looks[r]) for _, r in NODATA if r != role]
        if last_fresh:
            rivals += [max(overlap(o, t) for t in composite(last_fresh))]
        worst = max(rivals) if rivals else 0.0
        return mine > worst, {"nodata": [round(mine, 3), round(worst, 3)]}
    want = {s: (t, r) for s, t, r in state}
    detail, ok = {}, True
    for slot in ORDER:
        exp = want.get(slot, ("", None))
        scores = {c: slot_score(o, slot, *c) for c in lexicon(
            slot, run_texts, exp[0])}
        best = max(scores.values())
        if exp not in scores:
            exp = ("", None)
        mine, mine_off = slot_score(o, slot, *exp, hidden_out=True)
        rival = max((v for c, v in scores.items() if c != exp), default=0.0)
        tied = mine >= best - 1e-9
        # A flash's off phase: the box is drawn, the text is not, and texts
        # of about the same width tie on the box alone. The frame shows a box
        # where the expected mode's box goes, and nothing that contradicts it.
        hidden = bool(exp[0]) and mine_off == mine and \
            mine_off >= best - HIDDEN_TOL and \
            (not tied or rival >= mine - 1e-9)
        if hidden:
            detail.setdefault("_hidden", []).append(slot)
        elif not tied:
            seen = max(scores, key=scores.get)
            detail[slot] = ["%s/%s" % seen, round(best, 3), round(mine, 3)]
            ok = False
        else:
            detail.setdefault("_margins", {})[slot] = round(mine - rival, 3)
    if ok:
        whole = max(overlap(o, t) for t in composite(state))
        nd = max(overlap(o, t) for t in _nodata_looks.values())
        if nd >= whole:
            ok = False
            detail["whole"] = ["NO AP DATA beats the fresh state", round(nd, 3),
                               round(whole, 3)]
    return ok, detail


def main():
    rows = [json.loads(l) for l in open(os.path.join(RUN, "bus.jsonl"))]
    rows.sort(key=lambda r: r["t"])
    frames = [json.loads(l) for l in open(os.path.join(RUN, "frames.jsonl"))]
    # Expected state at each grab, every state the bus passed through in the
    # second before it, and the last fresh state (for NO AP DATA).
    # Every state change of the run, with the last fresh state before it.
    changes = []
    rp = Replay(rows)
    last_fresh = ()
    while rp.i < len(rows):
        t = rows[rp.i]["t"]
        rp.advance(t)
        st = rp.expected()
        if not changes or changes[-1][1] != st:
            changes.append((t, st, last_fresh))
        if st and st[0][0] != "nodata":
            last_fresh = st
    times = [c[0] for c in changes]
    exp = []
    for fr in frames:
        t, t_end = fr["t"], fr.get("t_end", fr["t"] + 0.5)
        i = bisect.bisect_right(times, t) - 1
        e, lf = (changes[i][1], changes[i][2]) if i >= 0 else ((), ())
        # States held at any moment from LAG_S before the grab to its end.
        j0 = max(0, bisect.bisect_right(times, t - LAG_S) - 1)
        j1 = bisect.bisect_right(times, t_end)
        near = [c[1] for c in changes[j0:j1]]
        recent = [s for s in dict.fromkeys(near) if s != e]
        exp.append((fr, e, recent, lf))
    run_texts = collections.defaultdict(set)
    for _, e, recent, _ in exp:
        for st in [e] + recent:
            for s, t, r in st:
                run_texts[s].add(t)
    out = open(os.path.join(RUN, "score.jsonl"), "w")
    tally = collections.Counter()
    results = []
    for fr, e, recent, lf in exp:
        img = QImage(os.path.join(RUN, "frames", fr["frame"]))
        if img.isNull():
            tally["unreadable"] += 1
            continue
        a = to_array(img.copy(X0, Y0, W, H))
        o = ink(a)
        luma = float(np.median(0.299 * a[..., 0] + 0.587 * a[..., 1]
                               + 0.114 * a[..., 2]))
        blank = luma > BLANK_LUMA
        if e == ():
            ok, detail = blank, {}
        elif blank:
            ok, detail = False, {"blank": "strip blank, bus has a state"}
        else:
            ok, detail = judge(o, e, run_texts, lf)
        verdict = "match" if ok else "MISMATCH"
        lag_of = None
        if not ok:
            for st in recent:
                if (st == () and blank) or (st and not blank and
                                            judge(o, st, run_texts, lf)[0]):
                    verdict, lag_of = "edge", label(st)
                    break
        tally[verdict] += 1
        row = dict(frame=fr["frame"], t=fr["t"], step=fr.get("step"),
                   expected=label(e), verdict=verdict, lag_of=lag_of,
                   luma=round(luma, 1), detail=detail)
        results.append((row, fr))
        out.write(json.dumps(row) + "\n")
    out.close()
    print("frames by verdict:", dict(tally))
    for row, _ in results:
        if row["verdict"] != "match":
            print("  %s %s expected %r lag_of %r %s" % (
                row["frame"], row["verdict"], row["expected"], row["lag_of"],
                json.dumps(row["detail"])))
    margins = collections.defaultdict(list)
    for row, _ in results:
        for slot, m in row["detail"].get("_margins", {}).items():
            if m > 0:
                margins[slot].append(m)
    print("per-slot margin of the expected look over the best other look "
          "(untied matches): " + ", ".join(
              "%s min %.3f" % (k, min(v)) for k, v in sorted(margins.items())))
    hid = [row for row, _ in results if row["detail"].get("_hidden")
           and row["verdict"] == "match"]
    print("matches with a slot in the flash's off phase (text hidden):", len(hid))
    nd = [row["detail"]["nodata"] for row, _ in results if "nodata" in row["detail"]]
    if nd:
        print("NO AP DATA frames: own look min %.3f, best rival max %.3f" % (
            min(x[0] for x in nd), max(x[1] for x in nd)))
    by_label = collections.OrderedDict()
    for row, fr in results:
        by_label.setdefault(row["expected"], []).append((row, fr))
    for k, v in by_label.items():
        shown = sum(1 for row, _ in v if not row["detail"].get("_hidden"))
        print("  %4d frames (%4d with every slot's text showing)  %s" % (
            len(v), shown, k))
    sheet(results)
    glass(results)


def caption_font(px):
    f = QFont("DejaVu Sans Mono")
    f.setPixelSize(px)
    return f


def sheet(results):
    """Each run of one expected strip: its first frame with the text showing
    (not a flash's off phase), and its last frame (the flash over), strip at
    1:1. Every non-match frame is added."""
    runs = []
    for i, (row, _) in enumerate(results):
        if not runs or results[runs[-1][0]][0]["expected"] != row["expected"]:
            runs.append([i])
        else:
            runs[-1].append(i)
    picks = []
    for run in runs:
        shown = [i for i in run if not results[i][0]["detail"].get("_hidden")]
        picks += [(shown or run)[0], run[-1]]
    picks += [i for i, (row, _) in enumerate(results) if row["verdict"] != "match"]
    picks = sorted(set(picks))
    cap = 22
    out = QImage(W, len(picks) * (H + cap + 6), QImage.Format.Format_RGB888)
    out.fill(QColor("#202020"))
    p = QPainter(out)
    p.setFont(caption_font(15))
    y = 0
    t0 = results[0][0]["t"]
    for i in picks:
        row, fr = results[i]
        img = QImage(os.path.join(RUN, "frames", fr["frame"])).copy(X0, Y0, W, H)
        p.setPen(QColor("#ff6060") if row["verdict"] == "MISMATCH" else QColor("#e0e0e0"))
        p.drawText(QRectF(4, y, W - 8, cap), Qt.AlignmentFlag.AlignVCenter,
                   "%s  +%5.0fs  bus: %s  ->  %s" % (
                       fr["frame"], row["t"] - t0, row["expected"], row["verdict"]))
        p.drawImage(0, y + cap, img)
        y += H + cap + 6
    p.end()
    out.save(os.path.join(RUN, "sheet.png"))
    print("sheet.png:", len(picks), "rows")


def glass(results):
    """Full frames at a third of full size, so the tape cues show with the
    strip: the middle frame of each of the twelve longest runs of one
    expected strip, in time order."""
    runs = []
    for i, (row, _) in enumerate(results):
        if not runs or results[runs[-1][0]][0]["expected"] != row["expected"]:
            runs.append([i])
        else:
            runs[-1].append(i)
    longest = sorted(sorted(runs, key=len, reverse=True)[:12], key=lambda r: r[0])
    picks = [r[len(r) // 2] for r in longest]
    sw, sh, cap = 640, 360, 20
    cols = 3
    rows_n = (len(picks) + cols - 1) // cols
    out = QImage(cols * sw, rows_n * (sh + cap), QImage.Format.Format_RGB888)
    out.fill(QColor("#202020"))
    p = QPainter(out)
    p.setFont(caption_font(12))
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for n, i in enumerate(picks):
        row, fr = results[i]
        x, y = (n % cols) * sw, (n // cols) * (sh + cap)
        p.setPen(QColor("#e0e0e0"))
        p.drawText(QRectF(x + 3, y, sw - 6, cap), Qt.AlignmentFlag.AlignVCenter,
                   "%s %s" % (fr["frame"], row["expected"]))
        img = QImage(os.path.join(RUN, "frames", fr["frame"]))
        p.drawImage(QRectF(x, y + cap, sw, sh), img)
    p.end()
    out.save(os.path.join(RUN, "glass.png"))
    print("glass.png:", len(picks), "frames")


if __name__ == "__main__":
    main()
