"""File-backed collection requests and worker health; no database required."""
import os
import time
import uuid
from storage import DATA_DIR, load_json, save_json, transaction

STATUS_PATH = os.path.join(DATA_DIR, 'collector_status.json')
REQUEST_PATH = os.path.join(DATA_DIR, 'collect_request.json')


@transaction
def request_collection():
    existing = load_json(REQUEST_PATH, None)
    if existing:
        return {'ok': True, 'queued': True, 'request_id': existing['id']}
    request = {'id': uuid.uuid4().hex, 'requested_at': time.time()}
    save_json(REQUEST_PATH, request)
    return {'ok': True, 'queued': True, 'request_id': request['id']}


@transaction
def finish_request(request):
    pending = load_json(REQUEST_PATH, None)
    if request and pending and pending['id'] == request['id']:
        os.unlink(REQUEST_PATH)


def collector_status():
    status = load_json(STATUS_PATH, {})
    now = time.time()
    age = now - status.get('heartbeat_at', 0)
    progress = now - (status.get('last_completed_at') or status.get('started_at', now))
    if not status:
        health = 'starting'
    elif age > 90:
        health = 'unresponsive'
    elif status.get('last_error') or progress > max(180, status.get('poll_interval_seconds', 300) * 3):
        health = 'degraded'
    else:
        health = 'healthy'
    return {**status, 'health': health, 'heartbeat_age_seconds': round(age, 1) if status else None,
            'request_pending': load_json(REQUEST_PATH, None) is not None}
