"""G79 cycle runner: repeats the entry-page and Clear-confirm sequences with
random 1.2-2.5 s spacing; never commits anything. argv: label cycles"""
import json, random, sys, time
from tap import tap
label, cycles = sys.argv[1], int(sys.argv[2])
OX, OY = 1260, 36
def key(col):
    return "xy:%d,%d" % (OX + col * 93 + 46, OY + 503 + 42)
SEQ = ["_footer_add", key(0), key(1), "_entry_clear", "_entry_cancel",
       "_footer_menu", "_menu_clear_request", "_close_menu"]
log = open("sends_%s.jsonl" % label, "a")
random.seed(5326)
for c in range(cycles):
    for i, name in enumerate(SEQ):
        r = tap(name, log)
        time.sleep(random.uniform(1.2, 2.5))
print("done", label, cycles)
