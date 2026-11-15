import os, socket
class Fix:
    def __init__(self, port=None):
        self.s = socket.create_connection(("127.0.0.1", int(port or os.environ.get("FIXPORT", "3490"))), timeout=3)
        self.f = self.s.makefile("rwb")
    def _cmd(self, line):
        self.f.write((line + "\n").encode()); self.f.flush()
        while True:
            r = self.f.readline().decode().strip()
            if r.startswith(line[:2]):
                return r
    def w(self, key, value):
        return self._cmd("@w%s;%s" % (key, value))
    def r(self, key):
        parts = self._cmd("@r%s" % key).split(";")
        val = parts[1] if len(parts) > 1 else None
        flags = parts[2] if len(parts) > 2 else ""
        return val, flags
