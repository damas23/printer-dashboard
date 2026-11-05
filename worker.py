"""Single independent collector; durable coalesced requests and heartbeat."""
import fcntl
import os
import signal
import threading
import time
import collector
import runtime
from storage import DATA_DIR, load_json, save_json


def main():
    config = load_json(collector.CONFIG_PATH, None)
    if not isinstance(config, dict) or not isinstance(config.get('printers'), list):
        raise SystemExit('Missing or invalid printer configuration')
    interval = int(config.get('poll_interval_seconds', 300))
    if interval < 10:
        raise SystemExit('poll_interval_seconds must be at least 10')
    os.makedirs(DATA_DIR, exist_ok=True)
    lock = open(os.path.join(DATA_DIR, '.collector.lock'), 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another collector is already running on this data directory')
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    status_lock = threading.Lock()
    status = {'started_at': time.time(), 'activity': 'starting', 'poll_interval_seconds': interval,
              'last_completed_at': None, 'last_error': None}

    def publish():
        with status_lock:
            status['heartbeat_at'] = time.time()
            save_json(runtime.STATUS_PATH, status)

    def heartbeat():
        while not stop.wait(30):
            publish()

    publish()
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    next_poll = 0
    try:
        while not stop.is_set():
            request = load_json(runtime.REQUEST_PATH, None)
            if time.monotonic() >= next_poll or request:
                started = time.monotonic()
                with status_lock:
                    status.update(activity='collecting', last_started_at=time.time())
                publish()
                try:
                    state = collector.run_once(config)
                    success = sum(bool(p.get('reachable')) for p in state['printers'])
                    with status_lock:
                        status.update(last_completed_at=time.time(), last_error=None,
                                      successful_printers=success, failed_printers=len(state['printers']) - success)
                    print(f'Poll completed: {success}/{len(state["printers"])} reachable', flush=True)
                except Exception as exc:
                    with status_lock:
                        status['last_error'] = str(exc)
                    print(f'Collection failed: {exc}', flush=True)
                finally:
                    runtime.finish_request(request)
                    next_poll = time.monotonic() + interval
                    with status_lock:
                        status.update(activity='idle', last_duration_seconds=round(time.monotonic() - started, 2))
                    publish()
            stop.wait(1)
    finally:
        stop.set()
        thread.join(timeout=2)
        with status_lock:
            status.update(activity='stopped', heartbeat_at=0)
            save_json(runtime.STATUS_PATH, status)
        lock.close()


if __name__ == '__main__':
    main()
