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


def test_fal_registered_and_headers(monkeypatch):
    monkeypatch.delenv("FAL_MODEL", raising=False)
    p = vp.get_video_provider("fal", api_key="k123")
    assert isinstance(p, vp.FalProvider)
    assert p._headers() == {"Authorization": "Key k123"}
    assert p.model == vp.FalProvider.DEFAULT_MODEL
    assert p.base_url == "https://queue.fal.run"


def test_mock_keyless():
    assert "mock" in vp.KEYLESS_PROVIDERS
    p = vp.get_video_provider("mock")  # 키 없이 생성 가능
    assert isinstance(p, vp.MockProvider)


def test_mock_generates_clip(tmp_path):
    p = vp.get_video_provider("mock")
    out = str(tmp_path / "c.mp4")
    p.generate("dreamy night city", out, duration=1, aspect="16:9")
    import os
    assert os.path.exists(out) and os.path.getsize(out) > 1000


# ─────────────────────────────────────────────────────────────
# 이미지 생성 provider (앨범 커버 등) — 영상용과는 별개 레지스트리
# ─────────────────────────────────────────────────────────────

def test_image_mock_keyless():
    assert "mock" in vp.IMAGE_KEYLESS_PROVIDERS
    p = vp.get_image_provider("mock")  # 키 없이 생성 가능
    assert isinstance(p, vp._MockImageProvider)


def test_image_mock_generates_image(tmp_path):
    p = vp.get_image_provider("mock")
    out = str(tmp_path / "cover.png")
    p.generate("a dreamy sunset, no text", out)
    import os
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_image_replicate_default_model(monkeypatch):
    monkeypatch.delenv("REPLICATE_IMAGE_MODEL", raising=False)
    p = vp.get_image_provider("replicate", api_key="test-key")
    assert isinstance(p, vp.ReplicateProvider)
    assert p.model == vp.DEFAULT_REPLICATE_IMAGE_MODEL
    assert p.base_url.startswith("https://api.replicate.com")


def test_image_replicate_model_override_via_kw(monkeypatch):
    monkeypatch.delenv("REPLICATE_IMAGE_MODEL", raising=False)
    p = vp.get_image_provider("replicate", api_key="test-key", model="custom/img-model")
    assert p.model == "custom/img-model"


def test_image_replicate_model_override_via_env(monkeypatch):
    monkeypatch.setenv("REPLICATE_IMAGE_MODEL", "env/img-model")
    p = vp.get_image_provider("replicate", api_key="test-key")
    assert p.model == "env/img-model"


def test_image_unknown_provider_raises():
    with pytest.raises(ValueError):
        vp.get_image_provider("does-not-exist", api_key="k")
