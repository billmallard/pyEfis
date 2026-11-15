cd ~/bench-scratch/pa15
P="python3 pa15_bench.py"; D=out5; mkdir -p $D
export DISPLAY=:0
echo "PROV $(git -C ~/src/pyEfis rev-parse --short HEAD) pid=$(systemctl --user show pyefis.service -p MainPID --value)"
tab(){ xdotool mousemove $1 14; sleep 0.3; xdotool mousedown 1; sleep 0.15; xdotool mouseup 1; sleep 2; }
lat(){ tag=$1; shift; $P drag "$@"; t0=$(date +%s.%N)
  for s in 0.1 0.3 0.6 1.0 2.0 4.0; do
    while [ "$(echo "$(date +%s.%N) - $t0 < $s" | bc)" = 1 ]; do sleep 0.02; done
    ffmpeg -loglevel error -y -f x11grab -video_size 670x1080 -i :0+1250,0 -frames:v 1 $D/${tag}_$s.png
  done; }
n=0
for rep in 1 2 3; do
  tab 1278; tab 1345
  n=$((n+1)); lat r${n}a_up_aftertab 1550 820 420 20 0.02 0.6
  n=$((n+1)); lat r${n}b_down 1550 300 700 20 0.02 0.6
  n=$((n+1)); lat r${n}c_up 1550 820 420 20 0.02 0.6
  n=$((n+1)); lat r${n}d_down 1550 300 700 20 0.02 0.6
done
echo "PROV $(git -C ~/src/pyEfis rev-parse --short HEAD) pid=$(systemctl --user show pyefis.service -p MainPID --value)"
