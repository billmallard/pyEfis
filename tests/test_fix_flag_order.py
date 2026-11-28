"""NFX1 (AER-6833): pyEfis's writes carry their quality flags in the order the
Net-FIX spec defines, ``ID;value;abfs`` (fix-gateway
doc/appendix/netfixascii.rst).

The pinned pyavtools sends annunciate, a literal 0, then bad and fail, so the
gateway records a panel's bad as fail, and a panel's fail as secfail with its
own fail cleared.  The first tests read the sentence DB_Item.output_value()
queues; the last ones send it to fix-gateway's real netfix server and
database at tests/arch/fix_gateway.pin and read the gateway's flags back.
"""

import importlib.util
import logging
import os
import pathlib
import socket
import subprocess
import sys
import time

import pytest

import pyavtools.fix

from pyefis import fix_watchdog

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_fix_writers", ROOT / "tools" / "check_fix_writers.py")
cfw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfw)

# (annunciate, bad, fail) on the panel's copy -> the flags field it sends.
CASES = [
    ((False, False, False), "0000"),
    ((False, True, False), "0100"),
    ((False, False, True), "0010"),
    ((False, True, True), "0110"),
    ((True, False, False), "1000"),
    ((True, True, True), "1110"),
]


class Sent:
    def __init__(self):
        self.lines = []

    def queue_out(self, data):
        self.lines.append(data.decode())


@pytest.fixture
def sent(monkeypatch):
    out = Sent()
    monkeypatch.setattr(pyavtools.fix, "db", out, raising=False)
    # pyavtools sets its module logger only when a Database is built.
    monkeypatch.setattr(pyavtools.fix, "log", logging.getLogger("pyavtools.fix"),
                        raising=False)
    return out


@pytest.fixture
def spec_order(monkeypatch):
    # Restore the class after the test: use_spec_flag_order patches it.
    monkeypatch.setattr(pyavtools.fix.DB_Item, "output_value",
                        pyavtools.fix.DB_Item.output_value)
    fix_watchdog.use_spec_flag_order()


def item(flags, key="BARO", value=29.92):
    it = pyavtools.fix.DB_Item(key, "float")
    it.min, it.max = 0.0, 100.0
    it.value = value
    it.annunciate, it.bad, it.fail = flags
    it.block_output = False
    return it


@pytest.mark.parametrize("flags, field", CASES)
def test_output_value_sends_abfs(sent, spec_order, flags, field):
    item(flags).output_value()
    assert sent.lines == ["BARO;29.92;%s\n" % field]


def test_a_pilot_write_through_the_value_setter_sends_abfs(sent, spec_order):
    # The 33 output_value() call sites and every `outputs:` onchange key go
    # through the same method; the setter is the onchange path.
    it = item((False, True, False))
    it.output = True
    it.value = 30.01
    assert sent.lines == ["BARO;30.01;0100\n"]


def test_a_just_received_value_is_still_not_echoed(sent, spec_order):
    it = item((False, False, False))
    it.block_output = True
    it.output_value()
    assert sent.lines == []
    it.output_value()
    assert sent.lines == ["BARO;29.92;0000\n"]


def test_upstream_output_value_still_misorders(sent):
    # The defect this override works around, in the pinned pyavtools.  When a
    # pyavtools bump makes this fail, the library sends abfs itself and
    # use_spec_flag_order can go.
    item((False, True, False)).output_value()
    item((False, False, True)).output_value()
    assert sent.lines == ["BARO;29.92;0010\n", "BARO;29.92;0001\n"]


# --- against fix-gateway's netfix server at the pin -----------------------

GATEWAY_DB = """
entries:
- key: BARO
  description: Altimeter Setting
  type: float
  min: 0.0
  max: 35.0
  units: inHg
  initial: 29.92
  tol: 2000

- key: ZZLOADER
  description: Last key
  type: str
  initial: "Loaded"
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def fixgw_src():
    """fix-gateway's src/fixgw at the pin, importable."""
    sha = cfw.read_pin()
    dest = cfw.cache_dir(sha).with_name("fix-gateway-src-" + sha[:12])
    try:
        checkout = cfw.fetch(sha, dest=dest, paths=["/src/fixgw/"])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        if os.environ.get("CI"):
            pytest.fail("could not fetch fix-gateway at the pin: %s" % e)
        pytest.skip("could not fetch fix-gateway at the pin (no network?)")
    src = str(checkout / "src")
    sys.path.insert(0, src)
    try:
        import fixgw.database
        import fixgw.plugins.netfix
        from fixgw import cfg
        assert pathlib.Path(fixgw.database.__file__).is_relative_to(checkout)
        yield fixgw.database, fixgw.plugins.netfix, cfg
    finally:
        sys.path.remove(src)


@pytest.fixture
def gateway(fixgw_src, tmp_path):
    database, netfix, cfg = fixgw_src
    db_file = tmp_path / "database.yaml"
    db_file.write_text(GATEWAY_DB)
    database.init(str(db_file))
    port = free_port()
    conf, meta = cfg.from_yaml(
        "type: server\nhost: 127.0.0.1\nport: %d\nbuffer_size: 1024\ntimeout: 1.0\n" % port,
        metadata=True)
    server = netfix.Plugin("netfix", conf, meta)
    server.start()
    sock = None
    try:
        deadline = time.monotonic() + 5
        while sock is None:
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            except ConnectionRefusedError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        yield database, sock
    finally:
        if sock is not None:
            sock.close()
        server.stop()
        database._stop_update_thread()


def gateway_flags(database, key):
    it = database.get_raw_item(key)
    return (bool(it.annunciate), bool(it.bad), bool(it.fail), bool(it.secfail))


def send_and_wait(sock, database, line, value):
    sock.sendall(line.encode())
    deadline = time.monotonic() + 5
    # The gateway item's value is (value, annunciate, old, bad, fail, secfail).
    while database.get_raw_item("BARO").value[0] != value:
        assert time.monotonic() < deadline, "the gateway never applied %r" % line
        time.sleep(0.02)


@pytest.mark.parametrize("flags", [c[0] for c in CASES])
def test_the_gateway_records_the_panels_flags(gateway, sent, spec_order, flags):
    database, sock = gateway
    it = item(flags, value=30.12)
    it.output_value()
    send_and_wait(sock, database, sent.lines[-1], 30.12)
    assert gateway_flags(database, "BARO") == flags + (False,)


def test_a_failed_panel_write_keeps_the_gateways_fail(gateway, sent, spec_order):
    # The reproduction: the gateway had failed the key, and the panel's copy
    # says so too.  Upstream's sentence set secfail and cleared fail.
    database, sock = gateway
    database.get_raw_item("BARO").fail = True
    item((False, False, True), value=30.05).output_value()
    send_and_wait(sock, database, sent.lines[-1], 30.05)
    assert gateway_flags(database, "BARO") == (False, False, True, False)
