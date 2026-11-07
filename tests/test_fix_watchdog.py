# CERT1 (AER-5031): a hung or reset FIX gateway must not leave the last
# attitude and air data on the glass as good.
#
# These tests run the REAL pyavtools Database and ClientThread against a
# fake gateway on a loopback socket.  The fake answers the client's
# start-up handshake (@l, @q, @s, @r) so every item has had one good frame,
# then either goes silent with the socket open (a deadlocked or SIGSTOPped
# fix-gateway) or resets the connection.

import importlib.util
import os
import socket
import threading
import time

import pytest

import pyavtools.fix
from pyavtools.fix import Database

from pyefis import fix_watchdog


def load_real_client():
    # conftest.py replaces pyavtools.fix.client with tests/mock_db/client
    # for every other test; these need the real socket client.
    path = os.path.join(os.path.dirname(pyavtools.fix.__file__), "client.py")
    spec = importlib.util.spec_from_file_location("_real_fix_client", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REAL_CLIENT = load_real_client()

PRIMARY_FLIGHT_KEYS = ["PITCH", "ROLL", "ALT", "IAS", "HEAD", "VS", "ALAT"]
OTHER_KEYS = ["OAT", "FUELQ1"]
ALL_KEYS = PRIMARY_FLIGHT_KEYS + OTHER_KEYS

TIMEOUT_S = 1.0
INTERVAL_S = 0.25
# The trip lands on the first tick at or after TIMEOUT_S of silence.
DEADLINE_MS = int((TIMEOUT_S + 2 * INTERVAL_S) * 1000)


class FakeGateway:
    """A Net-FIX server holding a fixed value for each key."""

    def __init__(self, keys):
        self.keys = keys
        self.values = {k: 12.5 for k in keys}
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.conn = None
        self.running = threading.Event()  # cleared = hung: no reads, no writes
        self.running.set()
        self.closed = False
        self.reads = 0
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _reply(self, line):
        if line.startswith("@l"):
            return "@l{0};0;{1}\n".format(len(self.keys), ",".join(self.keys))
        key = line[2:].strip()
        if line.startswith("@q"):
            return "@q{0};{0} desc;float;-100000;100000;x;1000;\n".format(key)
        if line.startswith("@s"):
            return "@s{0}\n".format(key)
        if line.startswith("@r"):
            self.reads += 1
            return "@r{0};{1};00000\n".format(key, self.values[key])
        return ""

    def _serve(self):
        try:
            self.conn, _ = self.listener.accept()
        except OSError:
            return
        buff = ""
        while not self.closed:
            self.running.wait()
            if self.closed:
                break
            self.conn.settimeout(0.05)
            try:
                data = self.conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            buff += data.decode()
            while "\n" in buff:
                line, buff = buff.split("\n", 1)
                if not self.running.is_set():
                    # Hung mid-buffer: keep the rest for the resume.
                    buff = line + "\n" + buff
                    break
                out = self._reply(line)
                if out:
                    try:
                        self.conn.sendall(out.encode())
                    except OSError:
                        return

    def hang(self):
        self.running.clear()

    def resume(self):
        self.running.set()

    def reset(self):
        """Close the connection with an RST and stop listening."""
        self.closed = True
        self.running.set()
        self.listener.close()
        if self.conn is not None:
            self.conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                 b"\x01\x00\x00\x00\x00\x00\x00\x00")
            self.conn.close()

    def close(self):
        if not self.closed:
            self.reset()


@pytest.fixture
def gateway_and_db(qtbot, monkeypatch):
    gw = FakeGateway(ALL_KEYS)
    monkeypatch.setattr(pyavtools.fix, "client", REAL_CLIENT)
    db = Database("127.0.0.1", gw.port)
    assert isinstance(db.clientthread, REAL_CLIENT.ClientThread)
    assert db.wait_for_initialization(5), "client never initialised"
    items = [db.get_item(k, wait=False) for k in ALL_KEYS]
    # One good frame per key: the @r answers clear the start-up fail flag.
    qtbot.waitUntil(lambda: not any(i.fail for i in items), timeout=3000)
    yield gw, db
    db.clientthread.getout = True
    gw.close()
    db.clientthread.join(5)
    # The client leaves its sender blocked on the queue when recv() errors
    # out (the RST path); release it or the non-daemon thread hangs exit.
    db.clientthread.sendqueue.put("exit")
    sender = getattr(db.clientthread, "sendthread", None)
    if sender is not None:
        sender.join(5)
    assert not db.clientthread.is_alive()


def primary_items(db):
    return [db.get_item(k, wait=False) for k in PRIMARY_FLIGHT_KEYS]


def all_items(db):
    return [db.get_item(k, wait=False) for k in ALL_KEYS]


def make_watchdog(db):
    w = fix_watchdog.FixLinkWatchdog(db, "PITCH", timeout=TIMEOUT_S,
                                     interval=INTERVAL_S)
    w.start()
    return w


def test_without_watchdog_hung_gateway_leaves_data_good(gateway_and_db, qtbot):
    # The defect, pinned against the pinned pyavtools: the client alone
    # never notices a gateway that stops talking with the socket open.
    gw, db = gateway_and_db
    gw.hang()
    qtbot.wait(DEADLINE_MS + 500)
    assert not any(i.fail for i in primary_items(db))


def test_hung_gateway_marks_primary_flight_data_failed(gateway_and_db, qtbot):
    gw, db = gateway_and_db
    w = make_watchdog(db)
    qtbot.wait(int(3 * INTERVAL_S * 1000))
    assert not w.tripped, "a live gateway must not trip the watchdog"
    assert not any(i.fail for i in all_items(db))

    gw.hang()
    hung_at = time.monotonic()
    qtbot.waitUntil(lambda: all(i.fail for i in primary_items(db)),
                    timeout=DEADLINE_MS)
    assert time.monotonic() - hung_at >= TIMEOUT_S - INTERVAL_S
    assert all(i.fail for i in all_items(db))
    assert w.tripped
    w.stop()


def test_reset_connection_marks_primary_flight_data_failed(gateway_and_db, qtbot):
    # A link that dies with an error: the client's recv() raises and it
    # drops into its reconnect loop without marking anything failed.
    gw, db = gateway_and_db
    w = make_watchdog(db)
    gw.reset()
    qtbot.waitUntil(lambda: all(i.fail for i in primary_items(db)),
                    timeout=DEADLINE_MS)
    assert w.tripped
    w.stop()


def test_next_good_frame_clears_the_failed_state(gateway_and_db, qtbot):
    gw, db = gateway_and_db
    w = make_watchdog(db)
    gw.hang()
    qtbot.waitUntil(lambda: w.tripped, timeout=DEADLINE_MS)
    assert all(i.fail for i in all_items(db))

    # Values that never change are not re-sent by a subscription; the
    # recovery re-read is what brings them back.
    gw.resume()
    qtbot.waitUntil(lambda: not any(i.fail for i in all_items(db)),
                    timeout=int(4 * INTERVAL_S * 1000))
    assert not w.tripped
    w.stop()


def test_item_keys_reads_the_real_database(gateway_and_db):
    # fix_watchdog.item_keys reads pyavtools' private item dict; this
    # fails if a pyavtools bump renames it.
    _gw, db = gateway_and_db
    assert set(fix_watchdog.item_keys(db)) >= set(ALL_KEYS)


class FakeItem:
    def __init__(self):
        self.timestamp = 0


class FakeDB:
    def __init__(self, keys=("PITCH",)):
        self.items = {k: FakeItem() for k in keys}
        self.sent = []
        self.failed = 0

    def get_item(self, key, wait=True):
        return self.items[key]

    def queue_out(self, data):
        self.sent.append(data)

    def mark_all_fail(self):
        self.failed += 1


def test_liveness_ignores_wall_clock_steps(qtbot):
    # The item timestamp is wall-clock (a GPS time set can step it back);
    # the watchdog only asks whether it changed, timed on its own clock.
    now = [100.0]
    db = FakeDB()
    w = fix_watchdog.FixLinkWatchdog(db, "PITCH", timeout=2.0, interval=0.5,
                                     clock=lambda: now[0])
    item = db.items["PITCH"]
    for t in (100.5, 101.0, 101.5):
        now[0] = t
        item.timestamp -= 3600  # a frame stamped an hour EARLIER still counts
        w.poll()
    assert db.failed == 0
    now[0] = 103.4
    w.poll()
    assert db.failed == 0
    now[0] = 103.6
    w.poll()
    assert db.failed == 1
    now[0] = 110.0
    w.poll()
    assert db.failed == 1, "mark_all_fail once per outage, not per tick"
    assert db.sent.count(b"@rPITCH\n") == 6


def test_start_picks_first_present_key_and_honours_config(qtbot):
    db = FakeDB(keys=("ALT",))
    w = fix_watchdog.start(db, {"FixLinkTimeout": 3})
    assert w.ping_key == "ALT" and w.timeout == 3.0
    w.stop()
    assert fix_watchdog.start(db, {"FixLinkTimeout": 0}) is None
    assert fix_watchdog.start(FakeDB(keys=("OAT",)), {}) is None
    w = fix_watchdog.start(FakeDB(keys=("OAT",)), {"FixLinkPingKey": "OAT"})
    assert w.ping_key == "OAT" and w.timeout == fix_watchdog.DEFAULT_TIMEOUT_S
    w.stop()
