"""렌더 잡 스토어 — 디스크 영속화 버전.

각 잡 폴더에 job.json 으로 메타를 저장해 재시작에도 살아남는다.
(Cloud Run 단일 인스턴스에서도 안전. 멀티 인스턴스/완전 영속은 GCS·Firestore 로
 교체 — 이 파일이 그 교체 지점이다.)
"""
import json
import os
import shutil
import threading
import time
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "jobs")
os.makedirs(DATA_DIR, exist_ok=True)

_JOBS = {}
_LOCK = threading.Lock()

# 공개 목록에 내보낼 슬림 필드 (무거운 log/assets 제외)
_PUBLIC_FIELDS = ("id", "status", "video", "thumb", "created", "title", "shorts")


def _job_file(jid):
    return os.path.join(DATA_DIR, jid, "job.json")


def _persist(jid):
    rec = _JOBS.get(jid)
    if not rec:
        return
    try:
        with open(_job_file(jid), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
    except OSError:
        pass


def load_all():
    """디스크의 job.json 들을 메모리로 로드 (재시작 복구)."""
    if not os.path.isdir(DATA_DIR):
        return
    for jid in os.listdir(DATA_DIR):
        jf = _job_file(jid)
        if os.path.exists(jf):
            try:
                with open(jf, encoding="utf-8") as f:
                    _JOBS[jid] = json.load(f)
            except (OSError, ValueError):
                pass


def create_job(title=""):
    jid = uuid.uuid4().hex[:12]
    d = os.path.join(DATA_DIR, jid)
    os.makedirs(d, exist_ok=True)
    with _LOCK:
        _JOBS[jid] = {
            "id": jid,
            "status": "queued",   # queued | running | done | error
            "progress": 0,        # 0~100 (running 중 ffmpeg 진행률)
            "error": None,
            "log": "",
            "video": False,
            "thumb": False,
            "opts": {},
            "assets": None,
            "title": title,
            "shorts": False,
            "created": time.time(),
        }
        _persist(jid)
    return jid, d


def update(jid, **kw):
    with _LOCK:
        if jid in _JOBS:
            _JOBS[jid].update(kw)
            _persist(jid)


def get(jid):
    with _LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else None


def job_dir(jid):
    return os.path.join(DATA_DIR, jid)


def list_jobs(limit=50):
    """최신순 슬림 목록 (히스토리 UI 용)."""
    with _LOCK:
        items = sorted(_JOBS.values(), key=lambda j: j.get("created", 0), reverse=True)
        return [{k: j.get(k) for k in _PUBLIC_FIELDS} for j in items[:limit]]


def cleanup(ttl_hours=24, keep=50):
    """TTL 초과 또는 개수 초과(오래된 것부터) 잡을 메모리·디스크에서 제거."""
    now = time.time()
    removed = 0
    with _LOCK:
        items = sorted(_JOBS.values(), key=lambda j: j.get("created", 0), reverse=True)
        for i, j in enumerate(items):
            age_h = (now - j.get("created", now)) / 3600
            if i >= keep or age_h > ttl_hours:
                jid = j["id"]
                _JOBS.pop(jid, None)
                shutil.rmtree(os.path.join(DATA_DIR, jid), ignore_errors=True)
                removed += 1
    return removed
