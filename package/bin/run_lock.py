"""One run at a time per input stanza.

splunkd starts a modular input again when configuration in the app changes
(another input created or enabled, a conf edited), even while the previous run
is still working. Two runs that both start from an empty checkpoint load the
same data twice: in CI every NHS row was indexed two to four times. The lock is
an exclusive, non-blocking flock on a file in the checkpoint directory, so it
is released when its process ends, however it ends.
"""
import os

try:
    import fcntl
except ImportError:  # Windows: no flock; runs are not serialised there
    fcntl = None


class RunLock:
    def __init__(self, checkpoint_dir, kind, name):
        safe = name.replace("://", "_").replace("/", "_")
        self.path = os.path.join(checkpoint_dir or ".", "%s_%s.lock" % (kind, safe))
        self._fh = None

    def acquire(self):
        """True if this run holds the lock; False if another run does."""
        if fcntl is None:
            return True
        self._fh = open(self.path, "a")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            return False
        return True

    def release(self):
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
