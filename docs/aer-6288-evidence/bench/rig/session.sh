# AER-6288 (AFC4 live) sim-bench hooks for sim_follow.py.  sh session.sh start|stop
# start: a PRIVATE fixgw (fix-gateway dev, the AFC2 adapter; its own config
#        tree, udp_in 49104, netfix 127.0.0.1:3594), a PRIVATE pyEfis (dev,
#        its own config tree) on Xvfb :7, then seq.py.
# stop:  stop seq.py, pyEfis, Xvfb and fixgw. Nothing here touches the live
#        fixgw, pyefis.service, display :0, their config trees or the bench
#        lock: the private gateway reads X-Plane over its own RREF subscriptions.
D=$(cd "$(dirname "$0")" && pwd)
W=$HOME/bench-scratch/aer6288
PY=$HOME/pyefis-venv/bin/python
DISP=:7
say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$D/session.log"; }
alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

case "$1" in
start)
    say "start: fgw $(git -C "$W/fgw" log --oneline -1) | pyEfis $(git -C "$W/pr" log --oneline -1)"
    if alive "$D/fixgw.pid"; then say "private fixgw already running"; exit 0; fi
    [ -e /tmp/.X11-unix/X7 ] && { say "REFUSED: display $DISP already exists"; exit 0; }
    rm -f "$D/STOP"
    setsid sh -c "echo \$\$ > '$D/fixgw.pid'; cd '$D'; exec env PYTHONPATH='$W/fgw/src' '$PY' -c 'import sys; from fixgw.server import main; sys.exit(main())' --config-file '$W/fcfg/default.yaml'" \
        > "$D/fixgw.log" 2>&1 < /dev/null &
    setsid Xvfb $DISP -screen 0 1920x1080x24 -nolisten tcp > "$D/xvfb.log" 2>&1 < /dev/null &
    echo $! > "$D/xvfb.pid"
    sleep 5
    if ! alive "$D/fixgw.pid"; then say "private fixgw did not start; NOT driving"; tail -5 "$D/fixgw.log" >> "$D/session.log"; sh "$0" stop; exit 0; fi
    setsid sh -c "echo \$\$ > '$D/pyefis.pid'; cd '$W/pr'; exec env QT_QPA_PLATFORM=xcb DISPLAY=$DISP PYTHONPATH='$W/pr/src' '$PY' pyEfis.py --config-file '$W/pcfg/default.yaml'" \
        > "$D/pyefis.log" 2>&1 < /dev/null &
    sleep 25
    if ! alive "$D/pyefis.pid"; then say "private pyEfis exited; NOT driving"; tail -5 "$D/pyefis.log" >> "$D/session.log"; sh "$0" stop; exit 0; fi
    setsid sh -c "echo \$\$ > '$D/seq.pid'; exec '$PY' '$W/seq.py' '$D' --port 3594 --display $DISP $SEQ_ARGS" \
        > "$D/seq.out" 2>&1 < /dev/null &
    sleep 1
    say "fixgw $(cat "$D/fixgw.pid"), Xvfb $(cat "$D/xvfb.pid"), pyEfis $(cat "$D/pyefis.pid"), seq $(cat "$D/seq.pid")"
    ;;
stop)
    touch "$D/STOP"
    sleep 4
    for p in seq pyefis xvfb fixgw; do
        if alive "$D/$p.pid"; then
            kill -TERM "$(cat "$D/$p.pid")" 2>/dev/null
            sleep 3
            alive "$D/$p.pid" && kill -KILL "$(cat "$D/$p.pid")" 2>/dev/null
        fi
        say "$p stopped: $(alive "$D/$p.pid" && echo NO || echo yes)"
    done
    say "stop: done, display :7 $([ -e /tmp/.X11-unix/X7 ] && echo 'STILL UP' || echo gone)"
    ;;
esac
