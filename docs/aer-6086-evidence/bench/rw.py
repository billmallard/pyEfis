import sys, os, time; sys.path.insert(0, os.path.expanduser("~/bench-scratch/aer6086/fgw/src"))
from fixgw.netfix import Client
c = Client("127.0.0.1", 3492); c.connect()
for a in sys.argv[1:]:
    if "=" in a:
        k, v = a.split("=", 1); c.write(k, v); time.sleep(0.1)
time.sleep(0.5)
for a in sys.argv[1:]:
    k = a.split("=", 1)[0]
    try: print(k, c.read(k))
    except Exception as e: print(k, "ERR", e)
