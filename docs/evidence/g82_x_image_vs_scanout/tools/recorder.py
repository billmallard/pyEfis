"""G82 X-image recorder: ffmpeg x11grab of a 32x32 patch at 60 fps, piped as
raw gray; each frame is stamped time.time() on arrival. Logs every frame
whose mean level changes state (dark < 64 < light < 192), plus a heartbeat
every 2 s so a recorder gap is visible. argv: out.jsonl x y [fps]"""
import json, os, subprocess, sys, time
out, x, y = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
fps = int(sys.argv[4]) if len(sys.argv) > 4 else 60
S = 32
cmd = ["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0",
       "-framerate", str(fps), "-video_size", "%dx%d" % (S, S),
       "-i", ":0.0+%d,%d" % (x - S // 2, y - S // 2),
       "-pix_fmt", "gray", "-f", "rawvideo", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, env=dict(os.environ, DISPLAY=":0"))
log = open(out, "w", buffering=1)
prev = None; n = 0; hb = 0; last = None
while True:
    b = p.stdout.read(S * S)
    t = time.time()
    if len(b) < S * S:
        break
    n += 1
    m = sum(b) / (S * S)
    st = "dark" if m < 64 else ("light" if m > 192 else "mid")
    if last is not None and t - last > 0.1:
        log.write(json.dumps({"k": "gap", "w": round(t, 4), "gap": round(t - last, 3)}) + "\n")
    last = t
    if st != prev:
        log.write(json.dumps({"k": "frame", "w": round(t, 4), "n": n, "st": st, "m": round(m, 1)}) + "\n")
        prev = st
    elif t - hb > 2:
        log.write(json.dumps({"k": "hb", "w": round(t, 4), "n": n}) + "\n"); hb = t
