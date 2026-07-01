"""영상 provider 레지스트리/추상화 테스트 (외부 API 호출 없음)."""
import pytest

import video_providers as vp


def test_replicate_registered():
    assert "replicate" in vp._PROVIDERS
    assert vp._PROVIDERS["replicate"] is vp.ReplicateProvider


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        vp.get_video_provider("does-not-exist")


def test_missing_key_raises(monkeypatch):
    # 키가 없으면 생성 단계에서 막혀야 한다 (httpx 부재/키 부재 모두 RuntimeError)
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        vp.get_video_provider("replicate")


def test_replicate_default_model(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-key")
    monkeypatch.delenv("REPLICATE_MODEL", raising=False)
    try:
        p = vp.get_video_provider("replicate")
    except RuntimeError as e:
        pytest.skip(f"httpx 미설치 등으로 생성 불가: {e}")
    assert p.model == vp.ReplicateProvider.DEFAULT_MODEL
    assert p.base_url.startswith("https://api.replicate.com")
