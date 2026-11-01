cd ~/bench-scratch/pa15
D=out_tabs; mkdir -p $D
export DISPLAY=:0
echo "PROV $(git -C ~/src/pyEfis rev-parse --short HEAD) pid=$(systemctl --user show pyefis.service -p MainPID --value)"
clk(){ xdotool mousemove $1 14; sleep 0.2; xdotool mousedown 1; sleep 0.05; xdotool mouseup 1; }
lat(){ tag=$1; t0=$(date +%s.%N)
  for s in 0.1 0.3 0.6 1.0 2.0; do
    while [ "$(echo "$(date +%s.%N) - $t0 < $s" | bc)" = 1 ]; do sleep 0.02; done
    ffmpeg -loglevel error -y -f x11grab -video_size 670x1080 -i :0+1250,0 -frames:v 1 $D/${tag}_$s.png
  done; }
for n in 1 2 3 4 5 6 7 8 9 10 11 12; do
  clk 1422; lat t${n}_eng; clk 1345; lat t${n}_fpl
done
echo "PROV $(git -C ~/src/pyEfis rev-parse --short HEAD) pid=$(systemctl --user show pyefis.service -p MainPID --value)"
