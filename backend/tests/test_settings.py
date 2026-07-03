"""settings 스토어 — 키 저장/유지/명시적 삭제(clear) 동작."""
import settings as st


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_DIR", str(tmp_path))
    monkeypatch.setattr(st, "_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(st, "_state", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)


def test_empty_key_keeps_existing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    st.update({"llm_api_key": "sk-test"})
    assert st.get_public()["llm_key_set"]
    st.update({"llm_api_key": ""})  # 빈 값은 삭제가 아니라 유지
    assert st.get_public()["llm_key_set"]


def test_explicit_clear_removes_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    st.update({"video_api_key": "r8_test"})
    assert st.get_public()["video_key_set"]
    st.update({"video_api_key_clear": True})
    assert not st.get_public()["video_key_set"]
    # clear=False 는 아무 것도 안 함
    st.update({"video_api_key": "r8_again", "video_api_key_clear": False})
    assert st.get_public()["video_key_set"]
