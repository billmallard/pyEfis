import glob, os
from unittest import mock
import yaml
from PyQt6.QtWidgets import QWidget
import pyefis.hmi as hmi
from pyefis.instruments import button

CONFIG = "src/pyefis/config"
FILES = sorted(glob.glob(f"{CONFIG}/buttons/*-invisible.yaml") + glob.glob(f"{CONFIG}/buttons/heading-bug-*.yaml") + [f"{CONFIG}/buttons/cdi-source.yaml"])

def test_draw(fix, qtbot):
    for k, lo, hi, v in (("TRIMP",-100,100,0),("TRIMR",-100,100,0),("TRIMY",-100,100,0),("DIM",0,100,50),("HEADBUG",0,360,90),("NAVSRC",0,3,0)):
        fix.db.define_item(k,k,"float",lo,hi,"",50000,""); fix.db.set_value(k,v)
        fix.db.get_item(k).bad=False; fix.db.get_item(k).fail=False
    for n in list(range(1,12))+list(range(27,34)):
        key=f"TSBTN1{n}"; fix.db.define_item(key,"b","bool",None,None,"",0,""); fix.db.set_value(key,False)
        fix.db.get_item(key).bad=False; fix.db.get_item(key).fail=False
    b = os.path.join(CONFIG,"databindings/default.yaml")
    items = (yaml.safe_load(open(b)) or {}).get("items")
    hmi.initialize({"databindings": items, "main": {"nodeID": 1}})
    out=[]
    for f in FILES:
        cfg=yaml.safe_load(open(f)); key=cfg["dbkey"].replace("{id}","1")
        p=QWidget(); p.screenName="PFD"; p.parent=mock.Mock(); p.parent.nodeID=1
        w=button.Button(p, config_file=f); qtbot.addWidget(p)
        p.resize(200,200); p.show(); w.resize(100,80); w.show(); qtbot.waitExposed(w)
        qtbot.wait(50); rest=w.grab().toImage()
        fix.db.set_value(key, True); qtbot.wait(30); held=w.grab().toImage(); held.save(os.path.join(os.environ["AB_OUT"], os.path.basename(f)+".held.png")); rest.save(os.path.join(os.environ["AB_OUT"], os.path.basename(f)+".rest.png"))
        fix.db.set_value(key, False); qtbot.wait(30); after=w.grab().toImage()
        out.append("%-34s held==rest %s  released==rest %s" % (os.path.basename(f), held==rest, after==rest))
        p.hide()
    print("\n"+"\n".join(out))
