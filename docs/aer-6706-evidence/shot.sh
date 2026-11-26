#!/bin/sh
# usage: shot.sh <name>  -- SIGUSR1 grab of the live window into ~/bench-scratch/efb4b/<name>.png
P=$(pgrep -f "pyefis-venv/bin/pyefis" | head -1)
rm -f /tmp/pyefis_screenshot.png
kill -USR1 $P; sleep 6
cp /tmp/pyefis_screenshot.png $HOME/bench-scratch/efb4b/$1.png && md5sum $HOME/bench-scratch/efb4b/$1.png
