"""MENU1 real-wire check: a REAL pyavtools client (no mock_db) in a pyEfis
process, a real fixgw netfix server (fix-gateway aer-5892/sysmenu-key on
127.0.0.1:3499), and a second netfix client writing SYSMENU like a control
head would. Prints what the menu did after each write."""
import socket, sys, time
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QObject, pyqtSignal
app = QApplication(sys.argv)
import pyavtools.fix as fix
import pyefis.system_menu as sm
print("pyavtools:", fix.__file__, "client:", sys.modules["pyavtools.fix.client"].__file__)
print("system_menu:", sm.__file__)
fix.initialize({"main": {"FixServer": "127.0.0.1", "FixPort": "3499"}})
fix.db.wait_for_initialization(10)

class Scr(QObject):
    screenShow = pyqtSignal(); screenHide = pyqtSignal()
    def __init__(s, n): super().__init__(); s.name = n; s.object = None
screens = [Scr("PFD")]
w = QWidget(); w.resize(1024, 600); w.running_screen = 0; w.show()
import threading
_orig = sm.SystemMenu.on_key
def _probe(self, v):
    print("  on_key thread:", threading.current_thread().name, "main?", threading.current_thread() is threading.main_thread())
    return _orig(self, v)
sm.SystemMenu.on_key = _probe
menu = sm.initialize(w, fix, screens)
print("key item:", getattr(menu, "key_item", None) is not None)

def pump(s=0.6):
    end = time.time() + s
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)

def write(v):
    c = socket.create_connection(("127.0.0.1", 3499), timeout=3)
    c.sendall(("@wSYSMENU;%s\n" % v).encode()); c.recv(100); c.close()

pump()
print("start: visible =", menu.isVisible())
write(1); pump(); print("after write true : visible =", menu.isVisible())
write(0); pump(); print("after write false: visible =", menu.isVisible())
menu.close_menu(); pump(0.2); print("closed by Close  : visible =", menu.isVisible())
write(1); pump(); print("second press     : visible =", menu.isVisible())
write(0); pump()
print("--- stopping fix")
fix.stop()
print("--- stopped")
