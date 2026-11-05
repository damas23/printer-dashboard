"""JSON persistence shared by the API and worker (local Linux volume only)."""
import fcntl
import functools
import json
import os
import tempfile
import threading
from contextlib import contextmanager

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
_THREAD_LOCK = threading.RLock()


def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.write-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def data_lock():
    """Serialize short read-modify-write transactions across threads/processes."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with _THREAD_LOCK, open(os.path.join(DATA_DIR, '.data.lock'), 'a') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def transaction(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with data_lock():
            return fn(*args, **kwargs)
    return wrapped
