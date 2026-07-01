"""잡 스토어 — 영속화/복구/목록/정리 (임시 DATA_DIR 로 격리)."""
import importlib
import time


def _fresh_jobs(tmp_path, monkeypatch):
    import jobs
    importlib.reload(jobs)
    monkeypatch.setattr(jobs, "DATA_DIR", str(tmp_path))
    jobs._JOBS.clear()
    return jobs


def test_create_update_get(tmp_path, monkeypatch):
    jobs = _fresh_jobs(tmp_path, monkeypatch)
    jid, d = jobs.create_job(title="곡")
    j = jobs.get(jid)
    assert j["title"] == "곡"
    assert j["status"] == "queued"
    assert j["progress"] == 0
    jobs.update(jid, status="running", progress=42)
    assert jobs.get(jid)["progress"] == 42


def test_persist_and_reload(tmp_path, monkeypatch):
    jobs = _fresh_jobs(tmp_path, monkeypatch)
    jid, _ = jobs.create_job(title="persist")
    jobs.update(jid, status="done", progress=100)
    # 메모리 비우고 디스크에서 복구
    jobs._JOBS.clear()
    jobs.load_all()
    j = jobs.get(jid)
    assert j is not None and j["status"] == "done" and j["progress"] == 100


def test_list_jobs_slim_fields(tmp_path, monkeypatch):
    jobs = _fresh_jobs(tmp_path, monkeypatch)
    jobs.create_job(title="a")
    jobs.create_job(title="b")
    lst = jobs.list_jobs()
    assert len(lst) == 2
    # 슬림 목록엔 무거운 log/assets 가 없어야 함
    assert "log" not in lst[0] and "assets" not in lst[0]
    assert "title" in lst[0] and "status" in lst[0]


def test_cleanup_by_count(tmp_path, monkeypatch):
    jobs = _fresh_jobs(tmp_path, monkeypatch)
    for i in range(5):
        jobs.create_job(title=str(i))
    removed = jobs.cleanup(ttl_hours=999, keep=2)
    assert removed == 3
    assert len(jobs.list_jobs()) == 2


def test_cleanup_by_ttl(tmp_path, monkeypatch):
    jobs = _fresh_jobs(tmp_path, monkeypatch)
    jid, _ = jobs.create_job(title="old")
    jobs.update(jid, created=time.time() - 48 * 3600)  # 48시간 전
    removed = jobs.cleanup(ttl_hours=24, keep=50)
    assert removed == 1
    assert jobs.get(jid) is None
