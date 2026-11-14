# k.py LABEL [KEYS...]: dump FIX keys (value;flags) to stdout and keys.log
import sys, time, fixgw.netfix as n
c = n.Client('127.0.0.1', 3490); c.connect()
keys = sys.argv[2:] or ['FPLSTATE','FPLACTLEG','FPLSEQ','FPLMSG','FPLPHASE','WPFROM','WPNAME','WPDIS','FPLCRS','FPLXTK','FPLCDI','CDISCALE','FPLAPR','FPLAPRTYPE','FPLTURN','LAT','LONG','GS','MAGVAR']
out = {}
for k in keys:
    try:
        r = c.read(k); out[k] = '%s|%s' % (r[1], ''.join(r[2:]) if len(r) > 2 else '')
    except Exception as e:
        out[k] = 'ERR %s' % e
line = '%s %s %s' % (time.strftime('%H:%M:%SZ', time.gmtime()), sys.argv[1], out)
print(line)
open('/home/pyefis/bench-scratch/aer1613/keys.log', 'a').write(line + '\n')
