cd ~/bench-scratch/pa15
P="python3 pa15_bench.py"; D=out3
export DISPLAY=:0
prov(){ echo "$(git -C ~/src/pyEfis rev-parse --short HEAD) pid=$(systemctl --user show pyefis.service -p MainPID --value) since=$(systemctl --user show pyefis.service -p ActiveEnterTimestamp --value)"; }
tab(){ xdotool mousemove $1 14; sleep 0.3; xdotool mousedown 1; sleep 0.15; xdotool mouseup 1; sleep 2; }
START=$(prov); echo "START $START"
case "$START" in f7b39d4*) ;; *) echo "NOT ON PA15 HEAD"; exit 3;; esac
mkdir -p $D; echo "$START" > $D/provenance.txt
$P act 2
tab 1278; tab 1345; sleep 1; $P shot $D a_top
$P drag 1550 820 420 20 0.02 0.6; sleep 0.8; $P shot $D b_d1_first_after_tab
$P drag 1550 820 420 20 0.02 0.6; sleep 0.8; $P shot $D c_d2
$P drag 1550 300 700 20 0.02 0.6; sleep 0.8; $P shot $D d_d3_down
$P drag 1550 300 700 20 0.02 0.6; sleep 0.8; $P shot $D e_d4_down
$P drag 1550 820 520 6 0.01 0; sleep 2.5; $P shot $D f_fling
tab 1278; tab 1345
$P drag 1550 300 700 20 0.02 0.6; sleep 0.8; $P shot $D g_d5_down_after_tab
$P drag 1550 250 950 20 0.02 0.6; $P drag 1550 250 950 20 0.02 0.6; sleep 0.8; $P shot $D h_top_clamped
$P click 1550 373; sleep 1.5; $P shot $D i_tap_menu
$P click 1584 634; sleep 1; $P shot $D j_cancelled
END=$(prov); echo "END $END"; echo "END $END" >> $D/provenance.txt
[ "$START" = "$END" ] || { echo "PROVENANCE CHANGED"; exit 4; }
