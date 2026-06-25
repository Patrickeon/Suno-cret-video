"""렌더 잡 스토어 (MVP: 인메모리 + 파일시스템).

추후 GCP 단계에서 DB/Cloud Tasks 로 교체 예정.
"""
import os
import threading
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "jobs")
os.makedirs(DATA_DIR, exist_ok=True)

_JOBS = {}
_LOCK = threading.Lock()


def create_job():
    jid = uuid.uuid4().hex[:12]
    d = os.path.join(DATA_DIR, jid)
    os.makedirs(d, exist_ok=True)
    with _LOCK:
        _JOBS[jid] = {
            "id": jid,
            "status": "queued",   # queued | running | done | error
            "error": None,
            "log": "",
            "video": False,
            "thumb": False,
            "opts": {},
        }
    return jid, d


def update(jid, **kw):
    with _LOCK:
        if jid in _JOBS:
            _JOBS[jid].update(kw)


def get(jid):
    with _LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else None


def job_dir(jid):
    return os.path.join(DATA_DIR, jid)
