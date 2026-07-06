"""로컬 데이터 경로 — MV_DATA_DIR 지정/기본값(문서 폴더) 동작."""
import os

import paths


def test_mv_data_dir_env_overrides(tmp_path, monkeypatch):
    custom = str(tmp_path / "custom-data")
    monkeypatch.setenv("MV_DATA_DIR", custom)
    d = paths.data_dir()
    assert d == custom
    assert os.path.isdir(custom)


def test_default_falls_back_to_documents(monkeypatch, tmp_path):
    monkeypatch.delenv("MV_DATA_DIR", raising=False)
    fake_docs = str(tmp_path / "Documents")
    monkeypatch.setattr(paths, "_documents_dir", lambda: fake_docs)
    d = paths.data_dir()
    assert d == os.path.join(fake_docs, "Suno MV Studio")
    assert os.path.isdir(d)


def test_documents_dir_returns_nonempty_path():
    # 실제 OS 문서 폴더 해석 — 존재 여부와 무관하게 문자열은 항상 나와야 한다
    assert paths._documents_dir()
