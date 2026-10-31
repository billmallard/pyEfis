#  Copyright (c) 2016 Phil Birkelbach
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

from PyQt6.QtGui import QColor
from PyQt6.QtCore import QObject, pyqtSignal, QEvent, QCoreApplication
from PyQt6.QtWidgets import QMainWindow, QApplication, QWidget

import os
import time
import importlib
import logging
import sys
import yaml
from pyefis import hmi
from pyefis import startup_notice
from pyefis.instruments import edit_focus
import pyavtools.fix as fix
import pyavtools.scheduler as scheduler

screens = []

# The nav-data management screen is always loaded, independent of the screen
# set in config (a panel/config push can drop it), but never booted: it is a
# click-through. See _ensure_data_status_screen().
DATA_STATUS_SCREEN = "DataStatus"

# This class is just a structure to hold information about a single
# screen that will be loaded.

class Screen(QObject):

    screenShow = pyqtSignal()
    screenHide = pyqtSignal()

    def __init__(self, name, module, config):
        super(Screen, self).__init__()
        self.name = name
        self.module = importlib.import_module(module)
        self.config = config

        # This would hold the instantiated Screen object from the module.
        self.object = None
        self.default = False

    def show(self):
        self.object.show()
        self.screenShow.emit()

    def hide(self):
        self.object.hide()
        self.screenHide.emit()


class Main(QMainWindow):
    keyPress = pyqtSignal(QEvent)
    keyRelease = pyqtSignal(QEvent)
    windowShow = pyqtSignal(QEvent)
    windowClose = pyqtSignal(QEvent)
    # change_asd_mode = pyqtSignal(QEvent)

    def __init__(self, config, config_path, preferences, parent=None):
        super(Main, self).__init__(parent)
        self.preferences = preferences
        self.config_path = config_path
        self.screenWidth = int(config["main"].get("screenWidth", False))
        self.screenHeight = int(config["main"].get("screenHeight", False))
        if not (self.screenWidth and self.screenHeight):
            # screenWidth and screenHeight are not defined in the config file
            # go full screen
            pscreen = QApplication.primaryScreen()
            if pscreen is None:
                # The platform plugin (eglfs) found no connected output --
                # e.g. a sleeping/disconnected HDMI panel drops hotplug
                # detect. Fail loudly here rather than dereferencing None;
                # the caller is responsible for making this failure
                # terminal so a process supervisor can see it and restart.
                raise RuntimeError(
                    "No display available: QApplication.primaryScreen() "
                    "returned None (platform plugin found no connected "
                    "output)"
                )
            screensize = pscreen.size()
            self.screenWidth = screensize.width()
            self.screenHeight = screensize.height()

        # Physical size of the panel, as asserted by whoever configured it
        # (the configurator writes this; hand-written configs may omit it).
        # Instruments use it to size text and touch targets in millimetres
        # rather than as a fraction of their own pane -- see
        # pyefis.display_metrics. Kept as None when absent or unparseable so
        # that module can fall through to Qt and then to a nominal DPI; a bad
        # value here must not become silently unreadable text.
        try:
            diag = config["main"].get("screenDiagonalInches", None)
            self.screenDiagonalInches = float(diag) if diag is not None else None
        except (TypeError, ValueError):
            self.screenDiagonalInches = None

        self.screenColor = config["main"]["screenColor"]
        # Panel-wide: dim edit icon on every touch-editable value at rest
        # (pyEfis #308). On by default (Bill, 2026-10-26: it tells the pilot
        # which values the knob can be pointed at).
        edit_focus.set_at_rest_hint(edit_focus.at_rest_hint_from_config(config["main"]))
        self.nodeID = config["main"].get('nodeID', 1)

        self.setObjectName("EFIS")
        self.resize(self.screenWidth, self.screenHeight)
        w = QWidget(self)
        w.setGeometry(0, 0, self.screenWidth, self.screenHeight)

        p = w.palette()
        if self.screenColor:
            p.setColor(w.backgroundRole(), QColor(self.screenColor))
            w.setPalette(p)
            w.setAutoFillBackground(True)
        # Init the variable to prvent exception in getRunningScreen()
        self.running_screen = None
        for idx, scr in enumerate(screens):

            scr.object = scr.module.Screen(self)
            setattr(scr.object, 'screenName', scr.name)
            log.debug("Loading Screen {0}".format(scr.name))
            # TODO Figure out how to have different size screens
            scr.object.resize(self.width(), self.height())
            scr.object.move(0, 0)
            if scr.default:
                scr.show()
                self.running_screen = idx
            else:
                scr.hide()
                # This is to force screen builder to parse its configs now
                # instead of waiting to do so just before it is first shown.
                # Without this the user will often see a delay when navigating
                # to a screen for the first time
                if callable(getattr(scr.object, 'initScreen', None)):
                    scr.object.initScreen()

    def showScreen(self, scr):
        found = None
        if type(scr) == int:
            if scr >= 0 and scr < len(screens):
                found = scr
        else:
            for i, s in enumerate(screens):
                if s.name == scr:
                    found = i
                    break
        if found is not None:
            if found != self.running_screen:  # Make sure it's different.
                screens[found].show()
                screens[self.running_screen].hide()
                self.running_screen = found
        else:
            raise KeyError("Screen {0} Not Found".format(scr))

    def showNextScreen(self, s=""):
        if self.running_screen == len(screens)-1:
            self.showScreen(0)
        else:
            self.showScreen(self.running_screen + 1)

    def showPrevScreen(self, s=""):
        if self.running_screen == 0:
            self.showScreen(len(screens)-1)
        else:
            self.showScreen(self.running_screen-1)

    def getRunningScreen(self, s=""):
        if getattr(self.running_screen, 'name', None):
            return screens[self.running_screen].name
        else:
            return 'Unknown'

    def doExit(self, s=""):
        # Ensure external processes are terminated before exiting
        # For example waydroid/weston if they are in use
        for s in screens:
            s.object.close()
        # Close down fix connections
        # This needs done before the main event loop is stopped below
        fix.stop()
        # Allow external processes to exit
        time.sleep(5)
        # This termiates the main event loop and can prevent
        # close events from finishing if called too soon
        QCoreApplication.quit()

    # We send signals for these events so everybody can play.
    def showEvent(self, event):
        self.windowShow.emit(event)

    def closeEvent(self, event):
        log.debug("Window Close event received")
        self.windowClose.emit(event)

    def keyPressEvent(self, event):
        self.keyPress.emit(event)

    def keyReleaseEvent(self, event):
        self.keyRelease.emit(event)

    # def change_asd_mode_event (self, event):
    #     self.change_asd_mode.emit(event)

    def get_config_item(self, child, key):
        for s in screens:
            if s.object == child:
                return s.config.get(key)
        else:
            return None

def setDefaultScreen(s):
    found = False
    if type(s) == int:
        for i, scr in enumerate(screens):
            if i == s:
                found = True
                scr.default = True
                log.debug("setting screen {0} to default".format(s))
            else:
                scr.default = False
    else:
        for scr in screens:
            if scr.name == s:
                found = True
                scr.default = True
                log.debug("setting screen {0} to default".format(s))
            else:
                scr.default = False
    return found


def _ensure_data_status_screen(config, configured_default):
    """Keep the nav-data management screen loaded, and boot the flight screen.

    The data-status screen used to be forced as the boot screen. It is a
    click-through, and pyEfis can restart in flight, so it no longer boots
    (BACKLOG L3): the flight screen boots directly and the startup notice is a
    banner drawn over it (``pyefis.startup_notice``).

    The screen is still guaranteed present -- the bundled definition is injected
    if a config push dropped it -- because the PFD data annunciation opens it,
    and its Continue button is pointed at the configured default flight screen.
    Returns the screen to boot. A configured default of DataStatus itself, or of
    a screen that is not loaded, is replaced by its Continue target, or failing
    that the first other screen, so no config boots to the click-through. Any failure falls back to
    ``configured_default`` so boot never breaks."""
    try:
        name = DATA_STATUS_SCREEN
        scr_config = config.setdefault("screens", {}).get(name)
        if scr_config is None:
            # A config push dropped it -- load the bundled definition so the
            # screen is always present regardless of the on-disk config.
            path = os.path.join(os.path.dirname(__file__), "config", "screens",
                                "datastatus.yaml")
            with open(path) as f:
                scr_config = (yaml.safe_load(f) or {}).get(name)
            if not scr_config:
                return configured_default
            config["screens"][name] = scr_config
            screens.append(Screen(name, scr_config["module"], scr_config))
            log.info("data-status: screen absent from config; "
                     "injected the bundled definition")
        names = [s.name for s in screens]
        boot = configured_default
        if isinstance(boot, int) and 0 <= boot < len(names):
            boot = names[boot]
        if boot == name or boot not in names:
            # Configured to boot the click-through (or a screen that is not
            # loaded, which would leave nothing on the glass): boot where its
            # Continue goes instead.
            target = None
            for inst in scr_config.get("instruments", []):
                if inst.get("type") == "data_status":
                    target = inst.get("options", {}).get("continue_screen")
            others = [n for n in names if n != name]
            log.warning("data-status: defaultScreen %r is the click-through "
                        "or not loaded", boot)
            boot = target if target in others else (others[0] if others
                                                    else name)
        else:
            # Continue proceeds to the configured default flight screen.
            for inst in scr_config.get("instruments", []):
                if inst.get("type") == "data_status":
                    inst.setdefault("options", {})["continue_screen"] = boot
        log.info("data-status: booting %s (data status reachable from the "
                 "annunciation)", boot)
        return boot
    except Exception as e:
        log.error("data-status: could not set up the built-in screen "
                  "(%s); using the configured default", e)
        return configured_default


def initialize(config, config_path, preferences):
    global mainWindow
    global log
    log = logging.getLogger(__name__)
    log.info("Initializing Graphics")
    # Load the Screens
    for each in config['screens']:
        module = config['screens'][each]["module"]
        try:
            name = each
            screens.append(Screen(name, module, config['screens'][each]))
            log.debug("Creating Screen {0}".format(name))
        except Exception as e:
            log.critical("Unable to load module - " + module + ": " + str(e))
            raise

    try:
        d = config["main"]["defaultScreen"]
    except KeyError:
        d = 0

    # The flight screen boots directly -- nothing blocking at boot, because
    # pyEfis can restart in flight. The nav-data screen stays loaded (the
    # annunciation opens it) with its Continue sent to the configured default.
    boot = _ensure_data_status_screen(config, d)
    setDefaultScreen(boot)

    mainWindow = Main(config, config_path, preferences)
    hmi.actions.showNextScreen.connect(mainWindow.showNextScreen)
    hmi.actions.showPrevScreen.connect(mainWindow.showPrevScreen)
    hmi.actions.showScreen.connect(mainWindow.showScreen)
    hmi.actions.doExit.connect(mainWindow.doExit)

    if 'menu' in config:
        menu = hmi.menu.Menu(mainWindow, config["menu"])
        menu.start()

    if 'FMS' in config:
        sys.path.insert(0, config["FMS"]["module_dir"])
        ui = importlib.import_module("qtui")
        uiwidget = ui.FMSUI(config["FMS"]["flight_plan_dir"], mainWindow)
        ui_width = 1000
        if 'ui_width' in config['FMS']:
            ui_width = config['FMS']['ui_width']
        uiwidget.resize(ui_width, 65)
        uiwidget.move(30, 32)
        menu.register_target("FMS", uiwidget)

    screen = bool(config["main"]["screenFullSize"])
    if screen:
        log.debug("Setting Screen to Full Size")
        mainWindow.showFullScreen()
    else:
        mainWindow.width = int(config["main"]["screenWidth"])
        mainWindow.height = int(config["main"]["screenHeight"])
        mainWindow.show()

    # Startup notice over the live flight screen: self-dismissing, transparent
    # to touch, never a modal (BACKLOG L3). Built after every other child so it
    # stacks on top.
    mainWindow.startupNotice = startup_notice.show_banner(mainWindow)


    def button_timeout():
        # set MENUTIMEOUT True
        button_key.value = True

    def button_timeout_reset():
        if not button_key.value:
            # When set to False reset timer
            button_timer.start()

    if config['main'].get('button_timeout', False):
        scheduler.initialize()
        button_timer = scheduler.scheduler.getTimer(config['main']['button_timeout'])
        if not button_timer:
            scheduler.scheduler.timers.append(scheduler.IntervalTimer(config['main']['button_timeout']))
            scheduler.scheduler.timers[-1].start()
            button_timer = scheduler.scheduler.getTimer(config['main']['button_timeout'])
        button_key = fix.db.get_item('HIDEBUTTON')
        button_timer.add_callback(button_timeout)
        button_key.valueWrite[bool].connect(button_timeout_reset)
