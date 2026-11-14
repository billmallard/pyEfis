"""Minimal netfix line client with reconnect (AER-809 FP8 session 2).
Survives a fixgw restart mid-flight: any socket error drops the connection
and the next call reconnects."""
import socket
import time


class NFX:
    def __init__(self, host="127.0.0.1", port=3490):
        self.addr = (host, port)
        self.s = self.f = None

    def _conn(self):
        if self.f is None:
            self.s = socket.create_connection(self.addr, timeout=3)
            self.f = self.s.makefile("rwb")

    def _drop(self):
        try:
            self.s.close()
        except Exception:
            pass
        self.s = self.f = None

    def cmd(self, line):
        for attempt in range(2):
            try:
                self._conn()
                self.f.write((line + "\n").encode())
                self.f.flush()
                while True:
                    r = self.f.readline().decode()
                    if not r:
                        raise OSError("closed")
                    r = r.strip()
                    if r.startswith(line[:2]):
                        return r
            except Exception:
                self._drop()
                if attempt:
                    raise
                time.sleep(0.5)

    def read(self, k):
        """-> (value_str, flags_str); ('ERR', '') if unreadable."""
        try:
            p = self.cmd("@r%s" % k).split(";")
            return p[1] if len(p) > 1 else "ERR", p[2] if len(p) > 2 else ""
        except Exception as e:
            return "ERR:%s" % type(e).__name__, ""

    def write(self, k, v):
        try:
            return self.cmd("@w%s;%s" % (k, v))
        except Exception as e:
            return "ERR:%s" % type(e).__name__
