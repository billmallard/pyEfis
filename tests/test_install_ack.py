"""The install / update notice step (BACKLOG L2, pyEfis half).

A fake ``pyefis-data`` stands in for the updater: it answers ``notice --json``
from a fixture and logs every other invocation, so these tests pin what pyEfis
decides (accepted for THIS version or not, install vs update) and that the
record is always left to ``pyefis-data accept``."""

import hashlib
import json
import sys

import pytest

from pyefis import __version__, install_ack

NOTICE = ("pyEfis is experimental software for Experimental / Amateur-Built "
          "aircraft. It is not certified. It is provided as-is with no warranty, "
          "and any use of it is at your own risk.")
SHA = hashlib.sha256(NOTICE.encode("utf-8")).hexdigest()


def _rec(software, sha=SHA, ts="2026-10-31T14:05:09Z"):
    return {"schema": 1, "event": "accept", "timestamp": ts, "notice_sha256": sha,
            "notice_text": NOTICE, "software": software, "packs": {},
            "user": "pi", "host": "pyefis", "via": "tty", "trigger": "install"}


def _fake_updater(tmp_path, records, accept_rc=0):
    doc = {"notice_id": "pyefis-software-2026-10-30", "notice_sha256": SHA,
           "notice": NOTICE, "accepted": False, "records": records}
    (tmp_path / "notice.json").write_text(json.dumps(doc))
    log = tmp_path / "calls.jsonl"
    exe = tmp_path / "pyefis-data"
    exe.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"if sys.argv[1:] == ['notice', '--json']:\n"
        f"    print(open({str(tmp_path / 'notice.json')!r}).read()); sys.exit(0)\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"sys.exit({accept_rc})\n")
    exe.chmod(0o755)
    return str(exe), log


def _calls(log):
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)


@pytest.fixture
def no_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)


def test_fresh_install_hands_the_accept_to_pyefis_data(tmp_path, tty):
    exe, log = _fake_updater(tmp_path, [_rec({"pyefis-data": "0.4.0"})])
    assert install_ack.main(["--pyefis-data", exe]) == 0
    assert _calls(log) == [["accept", "--trigger", "pyefis-install",
                            "--software", f"pyefis={__version__}"]]


def test_new_pyefis_version_is_an_update_and_needs_a_new_accept(tmp_path, tty):
    exe, log = _fake_updater(tmp_path, [_rec({"pyefis-data": "0.4.0", "pyefis": "0.0.1"})])
    assert install_ack.main(["--pyefis-data", exe]) == 0
    assert _calls(log) == [["accept", "--trigger", "pyefis-update",
                            "--software", f"pyefis={__version__}"]]


def test_already_accepted_for_this_version_asks_nothing(tmp_path, tty, capsys):
    exe, log = _fake_updater(tmp_path, [_rec({"pyefis-data": "0.4.0", "pyefis": __version__})])
    assert install_ack.main(["--pyefis-data", exe]) == 0
    assert _calls(log) == []
    assert "already accepted" in capsys.readouterr().out


def test_accept_of_an_older_notice_text_does_not_count(tmp_path, tty):
    stale = _rec({"pyefis-data": "0.4.0", "pyefis": __version__}, sha="0" * 64)
    exe, log = _fake_updater(tmp_path, [stale])
    assert install_ack.main(["--pyefis-data", exe]) == 0
    assert _calls(log)[0][0] == "accept"


def test_no_terminal_stops_without_recording(tmp_path, no_tty, capsys):
    exe, log = _fake_updater(tmp_path, [])
    assert install_ack.main(["--pyefis-data", exe]) == install_ack.NOT_ACCEPTED_RC
    assert _calls(log) == []
    assert NOTICE in capsys.readouterr().err           # the full text, even here


def test_decline_propagates_pyefis_data_exit_code(tmp_path, tty):
    exe, log = _fake_updater(tmp_path, [], accept_rc=3)
    assert install_ack.main(["--pyefis-data", exe]) == 3
    assert len(_calls(log)) == 1


def test_check_reports_without_prompting(tmp_path, tty):
    exe, log = _fake_updater(tmp_path, [])
    assert install_ack.main(["--pyefis-data", exe, "--check"]) == install_ack.NOT_ACCEPTED_RC
    assert _calls(log) == []
    exe, log = _fake_updater(tmp_path, [_rec({"pyefis-data": "0.4.0", "pyefis": __version__})])
    assert install_ack.main(["--pyefis-data", exe, "--check"]) == 0


def test_missing_updater_is_an_error_not_an_accept(tmp_path, tty, monkeypatch):
    monkeypatch.delenv("PYEFIS_DATA", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert install_ack.main([]) == install_ack.UPDATER_RC


def test_updater_without_notice_command_is_an_error(tmp_path, tty):
    exe = tmp_path / "pyefis-data"
    exe.write_text(f"#!{sys.executable}\nimport sys; sys.exit(2)\n")
    exe.chmod(0o755)
    assert install_ack.main(["--pyefis-data", str(exe)]) == install_ack.UPDATER_RC


def test_env_var_names_the_updater(tmp_path, tty, monkeypatch):
    exe, log = _fake_updater(tmp_path, [])
    monkeypatch.setenv("PYEFIS_DATA", exe)
    assert install_ack.main([]) == 0
    assert _calls(log)[0][0] == "accept"
