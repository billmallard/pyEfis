"""G82: a 4x4 always-on-top window at the screen corner. It clips the fullscreen
pyEfis window, so the X server cannot page-flip it (Present falls back to copy)."""
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication(sys.argv)
w = QWidget(); w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.X11BypassWindowManagerHint)
w.setStyleSheet("background:black;"); w.setGeometry(0, 1076, 4, 4); w.show()
app.exec()
