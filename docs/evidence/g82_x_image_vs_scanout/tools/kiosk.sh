#!/bin/sh
# G82 rerun on the bench kiosk itself (PageFlip off), both recorders. Run under the bench lock.
L=$1; cd ~/bench-scratch/aer5478/g79; export DISPLAY=:0
grep -q "issue=AER-5478" ~/.bench-claim || { echo "claim is not AER-5478"; exit 9; }
P=$(systemctl --user show -p MainPID --value pyefis)
for k in 1 2 3; do xdotool mousemove 1344 12 click 1; sleep 2; xdotool mousemove 1900 600; sleep 1
  grep fp_targets /tmp/g79_probe.log | tail -1 | grep -q "\"page\": \"fpl\"" && break; done
grep fp_targets /tmp/g79_probe.log | tail -1 | grep -q "\"page\": \"fpl\"" || { echo "FPL tab not open"; exit 3; }
echo "start $(date -u +%FT%T.%NZ) kiosk_head=$(git -C ~/src/pyEfis rev-parse --short HEAD) pyefis=$P pageflip=$(grep -c "\"PageFlip\" \"off\"" /var/log/Xorg.0.log) load=$(cut -d" " -f1-3 /proc/loadavg)" >> prov_$L.txt
mkdir -p glass_$L glass_${L}k
setsid -f ~/pyefis-venv/bin/python glassrec.py glass_$L 1260 36 648 1004 30 </dev/null >glass_$L/rec.err 2>&1
setsid -f ~/pyefis-venv/bin/python kmsrec.py glass_${L}k 1260 36 648 1004 30 </dev/null >glass_${L}k/rec.err 2>&1
sleep 2; python3 cycle.py $L 12; sleep 3
pkill -f "[g]lassrec.py glass_$L"; sudo -n pkill -f "[k]msgrab"
echo "end $(date -u +%FT%T.%NZ) pyefis=$(systemctl --user show -p MainPID --value pyefis)" >> prov_$L.txt
cp /tmp/g79_probe.log probe_$L.log; cp probe_$L.log probe.log
~/pyefis-venv/bin/python analyze.py . $L > analyze_$L.txt
ln -sf sends_$L.jsonl sends_${L}k.jsonl; ~/pyefis-venv/bin/python analyze.py . ${L}k > analyze_${L}k.txt
tail -7 analyze_$L.txt; echo "== scanout"; tail -7 analyze_${L}k.txt; cat prov_$L.txt; echo KIOSK-DONE
