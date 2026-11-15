import json, os, sys
for L in sys.argv[1:]:
    x=json.load(open("rows_%s.json"%L)); k=json.load(open("rows_%sk.json"%L)) if os.path.exists("rows_%sk.json"%L) else None
    late=lambda r: r["i"]>0 and (r["glass"] is None or r["glass"]>0.2)
    xl=[r["i"] for r in x if late(r)]
    out="%-8s X late(>0.2s, taps 1-95)=%2d %s" % (L, len(xl), xl)
    if k:
        kl=[(r["i"],r["glass"]) for r in k if r["i"]>0 and (r["glass"] is None or r["glass"]>0.3)]
        d=sorted(b["glass"]-a["glass"] for a,b in zip(x,k) if a["glass"] and b["glass"] and not late(a) and a["i"]>0)
        out+="\n          scanout >0.3 s: %s ; scanout max (taps 1-95) %.3f ; scanout-X offset, on-time taps: median %.3f [%.3f, %.3f]" % (kl, max(r["glass"] for r in k if r["i"]>0), d[len(d)//2], d[0], d[-1])
    print(out)
