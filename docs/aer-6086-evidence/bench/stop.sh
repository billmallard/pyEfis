#!/bin/bash
S=$HOME/bench-scratch/aer6086/run
for n in feeder pyefis xvfb fixgw; do [ -f $S/$n.pid ] && kill $(cat $S/$n.pid) 2>/dev/null && echo stopped $n; done
