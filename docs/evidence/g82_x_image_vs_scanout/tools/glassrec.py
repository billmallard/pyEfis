"""Timestamped glass recorder for G79. ffmpeg x11grab of a region -> raw gray
frames on a pipe; each frame is stamped time.time() on arrival and compared
with the previous one. Writes one JSON line per frame whose content changed
(and a heartbeat every 2 s), and keeps every changed frame as .npy for
inspection. argv: out_dir x y w h fps"""
import json, os, subprocess, sys, time
import numpy as np
out, x, y, w, h, fps = sys.argv[1], *map(int, sys.argv[2:7])
os.makedirs(out, exist_ok=True)
cmd = ["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0",
       "-framerate", str(fps), "-video_size", "%dx%d" % (w, h), "-i", ":0.0+%d,%d" % (x, y),
       "-pix_fmt", "gray", "-f", "rawvideo", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, env=dict(os.environ, DISPLAY=":0"))
log = open(os.path.join(out, "glass.jsonl"), "a", buffering=1)
prev = None; n = 0; last_hb = 0
size = w * h
while True:
    buf = p.stdout.read(size)
    t = time.time()
    if len(buf) < size:
        break
    a = np.frombuffer(buf, np.uint8).reshape(h, w)
    n += 1
    if prev is None or not np.array_equal(a, prev):
        d = -1 if prev is None else int(np.count_nonzero(a != prev))
        np.save(os.path.join(out, "f%06d.npy" % n), a.reshape(h // 4, 4, w // 4, 4).mean(axis=(1, 3)).astype(np.uint8) if h % 4 == 0 and w % 4 == 0 else a[::4, ::4])
        log.write(json.dumps({"w": round(t, 4), "n": n, "changed_px": d}) + "\n")
        prev = a
    elif t - last_hb > 2:
        log.write(json.dumps({"w": round(t, 4), "n": n, "hb": 1}) + "\n")
        last_hb = t
