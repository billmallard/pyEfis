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
from pyefis import fix_watchdog
from pyefis import startup_notice
from pyefis.instruments import edit_focus
import pyavtools.fix as fix
import pyavtools.scheduler as scheduler

screens = []

# The nav-data management screen is always loaded, independent of the screen
# set in config (a panel/config push can drop it). It boots only when the
# aircraft is known to be on the ground (BACKLOG BOOT1); see
# _ensure_data_status_screen() and _boot_on_ground().
DATA_STATUS_SCREEN = "DataStatus"
# How long boot waits for a valid airspeed before giving up and booting the
# flight screen (BOOT1). The gateway answers the initial reads within
# milliseconds when the sensor is live, so this is only spent when IAS is
# missing or flagged -- the case that must not read as "on the ground".
BOOT_GROUND_WAIT_S = 3.0
# After IAS first reads valid and slow, let the other initial reads (GS, the
# Vgnd aux) land before deciding, so a moving GPS is not missed by a race.
BOOT_GROUND_SETTLE_S = 0.25
# Built-in About/System screen (BACKLOG L4); see _ensure_about_screen().
ABOUT_SCREEN = "About"

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

    def __init__(self, config, config_path, preferences, parent=None,
                 flight_screen=None):
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
        # Screens whose build raised and were dropped (AER-6106); showScreen
        # turns a jump to one of them into a logged no-op.
        self.dropped_screens = []
        flight = flight_screen if flight_screen is not None else next(
            (s.name for s in screens if s.default), None)
        if isinstance(flight, int) and 0 <= flight < len(screens):
            flight = screens[flight].name
        for scr in list(screens):
            if scr.name == flight:
                # Nothing to fall back to: let the fault stop the process so
                # the supervisor sees it.
                self._build_screen(scr)
                continue
            # Any other screen -- data status, About, a map -- is built inside
            # a guard, so one constructor fault costs that screen only and not
            # the flight screen with it (brief R3; AER-6106). A screen that
            # raised mid-build may have left a widget parented to the window;
            # remove it so it cannot paint over the screen that boots.
            before = set(self.children())
            try:
                self._build_screen(scr)
            except Exception:
                log.exception("screen %s failed to build; dropped, the other "
                              "screens carry on", scr.name)
                for child in set(self.children()) - before:
                    if isinstance(child, QWidget):
                        child.hide()
                    child.deleteLater()
                screens.remove(scr)
                self.dropped_screens.append(scr.name)
        if screens and not any(s.default for s in screens):
            # The boot screen was dropped (data status on a ground boot):
            # boot the flight screen instead.
            if not setDefaultScreen(flight):
                screens[0].default = True
            log.warning("boot screen dropped; booting %s instead",
                        next(s.name for s in screens if s.default))
        for idx, scr in enumerate(screens):
            if scr.default:
                scr.show()
                self.running_screen = idx
            else:
                scr.hide()

    def _build_screen(self, scr):
        scr.object = scr.module.Screen(self)
        setattr(scr.object, 'screenName', scr.name)
        log.debug("Loading Screen {0}".format(scr.name))
        # TODO Figure out how to have different size screens
        scr.object.resize(self.width(), self.height())
        scr.object.move(0, 0)
        # Force screen builder to parse its configs and build its instruments
        # now, inside the caller's guard, instead of waiting until the screen
        # is first shown. Without this the user will often see a delay when
        # navigating to a screen for the first time, and a fault in the boot
        # screen's instruments would surface outside any guard.
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
        if found is None and scr in getattr(self, 'dropped_screens', ()):
            # A button or annunciation pointing at a screen that failed to
            # build must not take the flight screen down with an exception
            # escaping a Qt slot.
            log.warning("screen %s was dropped at boot; not shown", scr)
            return
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
    """Keep the nav-data management screen loaded; return the flight screen.

    pyEfis can restart in flight, so the data-status screen is never booted
    blindly (BACKLOG L3). Whether it boots at all is decided separately by
    ``_boot_on_ground`` (BACKLOG BOOT1): on the ground it is shown first, as in
    a normal start sequence; moving, or with airspeed unknown, the flight
    screen this function returns boots directly. Either way the startup notice
    is a banner drawn over whichever screen boots (``pyefis.startup_notice``).

    The screen is guaranteed present -- the bundled definition is injected if a
    config push dropped it -- because the PFD data annunciation opens it, and
    its Continue button is pointed at the configured default flight screen.
    Returns the flight screen. A configured default of DataStatus itself, or of
    a screen that is not loaded, is replaced by its Continue target, or failing
    that the first other screen, so the flight screen is never the
    click-through. Any failure falls back to ``configured_default`` so boot
    never breaks."""
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
        log.info("data-status: flight screen is %s", boot)
        return boot
    except Exception as e:
        log.error("data-status: could not set up the built-in screen "
                  "(%s); using the configured default", e)
        return configured_default


def _valid(item):
    return not (item.bad or item.fail or item.old)


def _ground_state(db):
    """Classify the aircraft for the boot screen choice (BACKLOG BOOT1).

    Returns ``"ground"`` only when IAS is valid (not bad, failed or old) and
    below ``IAS.Vgnd``, the aircraft's on-ground IAS limit. Returns
    ``"moving"`` when IAS is at or above it, when valid GPS groundspeed is at
    or above it (a blocked pitot in flight reads slow), or when the IAS key or
    its Vgnd aux is not defined at all -- a failed sensor must never read as
    "on the ground". Returns None while it cannot tell yet: IAS flagged, or
    the Vgnd value not read; the caller's wait turns that into the flight
    screen.

    The groundspeed figure is Vgnd itself: it is the aircraft's own "may be on
    the ground" speed, above any taxi speed. GS is used only to force the
    flight screen, never to declare the aircraft on the ground -- AC 20-165B
    3.10.2 Note 1 warns that a groundspeed threshold alone gives false
    air-ground status, so it may only bias toward the safe side."""
    try:
        ias = db.get_item("IAS", wait=False)
    except Exception:
        return "moving"
    if "Vgnd" not in ias.get_aux_list():
        return "moving"
    vgnd = ias.get_aux_value("Vgnd")
    if vgnd is None:
        return None
    vgnd = float(vgnd)
    try:
        gs = db.get_item("GS", wait=False)
    except Exception:
        gs = None
    if gs is not None and _valid(gs) and float(gs.value) >= vgnd:
        return "moving"
    if not _valid(ias):
        return None
    return "moving" if float(ias.value) >= vgnd else "ground"


def _boot_on_ground(wait_s=BOOT_GROUND_WAIT_S, settle_s=BOOT_GROUND_SETTLE_S,
                    clock=time.monotonic, sleep=time.sleep):
    """True when the data-status screen should boot (BACKLOG BOOT1).

    Polls ``_ground_state`` until it is known. "moving" returns False at once;
    "ground" must hold for ``settle_s`` so the GS and Vgnd initial reads have
    landed; still unknown after ``wait_s`` returns False. Every failure path,
    including an exception, falls toward the flight screen."""
    try:
        deadline = clock() + wait_s
        settled_at = None
        while True:
            state = _ground_state(fix.db)
            if state == "moving":
                log.info("boot: aircraft moving; booting the flight screen")
                return False
            if state == "ground":
                if settled_at is None:
                    settled_at = clock() + settle_s
                elif clock() >= settled_at:
                    log.info("boot: on the ground; booting data status")
                    return True
            else:
                settled_at = None
                if clock() >= deadline:
                    log.warning("boot: no valid airspeed within %.1f s; "
                                "booting the flight screen", wait_s)
                    return False
            sleep(0.05)
    except Exception as e:
        log.error("boot: ground check failed (%s); booting the flight "
                  "screen", e)
        return False


class _GroundBootWatch(QObject):
    """Leave the boot data-status screen when the aircraft moves (BOOT1).

    Taxi-out and takeoff never need Continue: as soon as ``_ground_state``
    reads "moving" while the boot data-status screen shows, the flight screen
    replaces it. The watch ends the first time that screen is left, so opening
    data status later from the annunciation is never cut short."""

    _SIGNALS = ("valueChanged", "auxChanged", "oldChanged", "badChanged",
                "failChanged")

    def __init__(self, window, flight_screen):
        super().__init__(window)
        self.window = window
        self.flight_screen = flight_screen
        self.active = True
        self._items = []
        for key in ("IAS", "GS"):
            try:
                item = fix.db.get_item(key, wait=False)
            except Exception:
                continue
            for name in self._SIGNALS:
                self._signal(item, name).connect(self.check)
            self._items.append(item)

    @staticmethod
    def _signal(item, name):
        sig = getattr(item, name)
        return sig[float] if name == "valueChanged" else sig

    def stop(self):
        self.active = False
        for item in self._items:
            for name in self._SIGNALS:
                try:
                    self._signal(item, name).disconnect(self.check)
                except (TypeError, RuntimeError):
                    pass
        self._items = []

    def check(self, *args):
        if not self.active:
            return
        running = self.window.running_screen
        if running is None or screens[running].name != DATA_STATUS_SCREEN:
            self.stop()
            return
        try:
            moving = _ground_state(fix.db) == "moving"
        except Exception:
            return
        if moving:
            log.info("boot: aircraft moving; leaving data status for %s",
                     self.flight_screen)
            self.stop()
            self.window.showScreen(self.flight_screen)


def _ensure_about_screen(config):
    """Guarantee the About/System screen (BACKLOG L4) is loaded.

    The notice must be reachable at any time without a reboot, so it cannot
    depend on a panel/config push keeping the screen in the screen set. If the
    config does not define it, inject the bundled definition. Returns True when
    the screen is present; any failure logs and returns False so boot never
    breaks."""
    try:
        if ABOUT_SCREEN in config.setdefault("screens", {}):
            return True
        path = os.path.join(os.path.dirname(__file__), "config", "screens",
                            "about.yaml")
        with open(path) as f:
            scr_config = (yaml.safe_load(f) or {}).get(ABOUT_SCREEN)
        if not scr_config:
            return False
        config["screens"][ABOUT_SCREEN] = scr_config
        screens.append(Screen(ABOUT_SCREEN, scr_config["module"], scr_config))
        log.info("about screen: absent from config; injected the bundled "
                 "definition")
        return True
    except Exception as e:
        log.error("about screen: could not load the built-in screen (%s)", e)
        return False


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

    # Data status boots only on the ground (valid IAS below IAS.Vgnd, GPS not
    # moving); otherwise the flight screen boots directly, because pyEfis can
    # restart in flight (BACKLOG L3, BOOT1). The nav-data screen stays loaded
    # (the annunciation opens it) with its Continue sent to the flight screen.
    flight = _ensure_data_status_screen(config, d)
    on_ground = (flight != DATA_STATUS_SCREEN
                 and DATA_STATUS_SCREEN in [s.name for s in screens]
                 and _boot_on_ground())
    boot = DATA_STATUS_SCREEN if on_ground else flight
    # bench-deploy.sh reads this line to report the booted screen.
    log.info("data-status: booting %s (%s)", boot,
             "on the ground; Continue goes to %s" % flight if on_ground
             else "data status reachable from the annunciation")
    setDefaultScreen(boot)
    _ensure_about_screen(config)

    mainWindow = Main(config, config_path, preferences, flight_screen=flight)
    mainWindow.groundBootWatch = (_GroundBootWatch(mainWindow, flight)
                                  if on_ground else None)
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

    # Startup notice over whichever screen booted: self-dismissing, transparent
    # to touch, never a modal (BACKLOG L3). Built after every other child so it
    # stacks on top.
    mainWindow.startupNotice = startup_notice.show_banner(mainWindow)
    # AER-5983: a link watchdog that is not running is shown, not just logged.
    mainWindow.linkMonitorCue = fix_watchdog.show_off_cue(
        mainWindow, fix_watchdog.off_reason)


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
