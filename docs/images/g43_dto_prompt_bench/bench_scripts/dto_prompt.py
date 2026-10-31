"""G43 (AER-4321, pyEfis #326): bench check that the Direct To page's
SELECT A WAYPOINT prompt clears once a waypoint is chosen and the direct-to
goes active.

X-Plane is idle on the bench, so a static position near KSBA is fed over
netfix at 2 Hz (as in bench_scripts/g42_dtk_mag.py). The script snapshots
the position keys first and writes them back at the end, cancels the
direct-to through the DTO page's Remove button (DTOX) and reopens the Map tab.

    python3 dto_prompt.py <outdir>     (run under the bench lock)
"""
import os
import subprocess
import sys
import threading
import time

from nfx import NFX

OUT = sys.argv[1]
POS = dict(LAT=34.4262, LONG=-119.8415, GS=0.0, HEAD=87.0, TRACK=87.0, MAGVAR=-11.9)
KEYS = ["FPLSTATE", "DTOID", "FPLCMD", "WPNAME", "FPLCRS", "COURSE", "LAT", "LONG"]
# 1920x1080 kiosk, right panel
TAB_FPL, TAB_MAP = (1346, 13), (1278, 12)
FPL_DIRECT_TO = (1503, 1005)
DTO_ACTIVATE = (1584, 1005)
KEY_R, KEY_Z, KEY_ENT = (1584, 733), (1677, 800), (1800, 935)

c = NFX()
stop = threading.Event()


def feeder():
    f = NFX()
    while not stop.is_set():
        for k, v in POS.items():
            f.write(k, v)
        time.sleep(0.5)


def tap(xy, settle=1.5):
    subprocess.run(["xdotool", "mousemove", str(xy[0]), str(xy[1]), "click", "1"],
                   env={"DISPLAY": ":0"}, check=True)
    time.sleep(settle)


def grab(name):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab",
                    "-video_size", "1920x1080", "-i", ":0", "-frames:v", "1",
                    os.path.join(OUT, name + ".png")], env={"DISPLAY": ":0"}, check=True)
    line = "%s %s %s" % (time.strftime("%H:%M:%S"), name,
                         {k: c.read(k)[0] for k in KEYS})
    print(line, flush=True)
    with open(os.path.join(OUT, "keys.log"), "a") as fh:
        fh.write(line + "\n")


os.makedirs(OUT, exist_ok=True)
saved = {k: c.read(k)[0] for k in POS}
print("saved", saved, flush=True)
th = threading.Thread(target=feeder, daemon=True)
th.start()
try:
    time.sleep(3)
    tap(TAB_FPL)
    tap(FPL_DIRECT_TO)
    grab("1_dto_page")
    tap(DTO_ACTIVATE)          # nothing selected
    grab("2_select_a_waypoint")
    tap(KEY_R)
    tap(KEY_Z)
    grab("3_typed_rz")
    tap(KEY_ENT, settle=4)     # FastFind RZS -> DTO
    grab("4_dto_active_fplpage")
    time.sleep(3)
    grab("5_dto_active_fplpage_plus3s")
finally:
    if c.read("FPLSTATE")[0] == "2":   # DTO page button reads Remove -> DTOX
        tap(TAB_FPL)
        tap(FPL_DIRECT_TO)
        tap(DTO_ACTIVATE, settle=3)
    stop.set()
    th.join()
    for k, v in saved.items():
        c.write(k, v)
    tap(TAB_MAP)
    grab("6_restored")
