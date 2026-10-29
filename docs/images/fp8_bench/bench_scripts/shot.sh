#!/bin/sh
# usage: shot.sh name  -> /home/pyefis/bench-scratch/aer809/shots/<name>.png + key dump
mkdir -p ~/bench-scratch/aer809/shots
DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -i :0 -frames:v 1 ~/bench-scratch/aer809/shots/$1.png
~/pyefis-venv/bin/python -c "
import fixgw.netfix as n,time; c=n.Client('127.0.0.1',3490); c.connect()
print(time.strftime('%H:%M:%S'),'$1',{k:c.read(k)[1][:9] for k in ['FPLSTATE','FPLACTLEG','WPFROM','WPNAME','WPDIS','FPLXTK','FPLCRS','EXTCRS','FPLCDI','EXTCDI','FPLTF','FPLPHASE','FPLAPR','CDISCALE','GPSSRC','COURSE','CDI','TOFROM','FPLMSG']})" | tee -a ~/bench-scratch/aer809/shots/keys.log
