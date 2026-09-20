"""render.build_command 의 옵션→CLI 매핑 테스트 (ffmpeg 실행 없음)."""
import os

import render


def _build(opts, lyrics="ly.txt", bg=None):
    cmd, out = render.build_command("/job", "a.mp3", lyrics, bg or [], opts)
    return cmd


def test_basic_required_flags():
    cmd = _build({})
    assert cmd[0].endswith("python") or "python" in cmd[0].lower() or cmd[0]
    assert "--audio" in cmd and "a.mp3" in cmd
    assert "--out" in cmd
    assert "--lyrics" in cmd


def test_viz_default_and_override():
    assert "waves" in _build({})
    cmd = _build({"viz": "spectrum"})
    assert cmd[cmd.index("--viz") + 1] == "spectrum"


def test_shorts_and_clip():
    cmd = _build({"shorts": True, "clip_start": "1:05", "clip_len": 20})
    assert "--shorts" in cmd
    assert cmd[cmd.index("--clip-start") + 1] == "1:05"
    assert cmd[cmd.index("--clip-len") + 1] == "20"


def test_no_kenburns_only_when_disabled():
    assert "--no-kenburns" not in _build({"kenburns": True})
    assert "--no-kenburns" in _build({"kenburns": False})


def test_video_bg_takes_precedence_over_images():
    cmd = _build({"video_bg": "clip.mp4"}, bg=["a.jpg", "b.jpg"])
    assert "--video-bg" in cmd and "clip.mp4" in cmd
    assert "--bg" not in cmd  # 영상 배경이 있으면 이미지 배경은 안 씀


def test_images_when_no_video_bg():
    cmd = _build({}, bg=["a.jpg", "b.jpg"])
    assert "--bg" in cmd
    i = cmd.index("--bg")
    assert cmd[i + 1] == "a.jpg" and cmd[i + 2] == "b.jpg"


def test_new_options_forwarded():
    cmd = _build({"bg_color": "0x111111", "intro": 2, "outro": 1.5, "align": "auto"})
    assert cmd[cmd.index("--bg-color") + 1] == "0x111111"
    assert cmd[cmd.index("--intro") + 1] == "2"
    assert cmd[cmd.index("--outro") + 1] == "1.5"
    assert cmd[cmd.index("--align") + 1] == "auto"


def test_lyrics_optional():
    cmd = render.build_command("/job", "a.mp3", None, [], {})[0]
    assert "--lyrics" not in cmd


def test_youtube_quality_options():
    cmd = _build({
        "res": "1440", "fps": 60, "normalize": True,
        "fade_in": 1.5, "fade_out": 2, "vignette": True, "film_grain": True,
    })
    assert cmd[cmd.index("--res") + 1] == "1440"
    assert cmd[cmd.index("--fps") + 1] == "60"
    assert "--normalize" in cmd
    assert cmd[cmd.index("--fade-in") + 1] == "1.5"
    assert cmd[cmd.index("--fade-out") + 1] == "2"
    assert "--vignette" in cmd
    assert "--film-grain" in cmd


def test_quality_defaults_omitted():
    # 기본값(1080/30/off)이면 플래그를 붙이지 않는다
    cmd = _build({"res": "1080", "fps": 30})
    assert "--res" not in cmd and "--fps" not in cmd
    assert "--normalize" not in cmd and "--vignette" not in cmd


def test_subtitle_style_options():
    cmd = _build({"sub_color": "FFD700", "sub_size": 1.2, "sub_pos": "top"})
    assert cmd[cmd.index("--sub-color") + 1] == "FFD700"
    assert cmd[cmd.index("--sub-size") + 1] == "1.2"
    assert cmd[cmd.index("--sub-pos") + 1] == "top"


def test_preview_and_logo_flags():
    cmd = _build({"preview": True, "logo": "/j/logo.png"})
    assert "--preview-secs" in cmd
    assert cmd[cmd.index("--logo") + 1] == "/j/logo.png"


def test_bg_pulse_flag():
    assert "--bg-pulse" in _build({"bg_pulse": True})
    assert "--bg-pulse" not in _build({})


def test_phase1_flags():
    cmd = _build({"sub_glow": True, "intro_card": True, "interlude_note": True,
                  "font": "NanumGothic"})
    assert "--sub-glow" in cmd
    assert "--intro-card" in cmd
    assert "--interlude-note" in cmd
    assert cmd[cmd.index("--font") + 1] == "NanumGothic"


def test_master_precedence_over_normalize():
    cmd = _build({"master": True, "normalize": True, "karaoke": True})
    assert "--master" in cmd
    assert "--normalize" not in cmd  # master 우선
    assert "--karaoke" in cmd


def test_normalize_when_no_master():
    cmd = _build({"normalize": True})
    assert "--normalize" in cmd and "--master" not in cmd


def test_subtitle_defaults_omitted():
    cmd = _build({"sub_color": "FFFFFF", "sub_size": 1.0, "sub_pos": "bottom"})
    assert "--sub-color" not in cmd
    assert "--sub-size" not in cmd
    assert "--sub-pos" not in cmd


def test_viz_color_string_and_list():
    cmd = _build({"viz_color": "FDA4AF,F9A8D4"})
    i = cmd.index("--viz-color")
    assert cmd[i + 1] == "FDA4AF" and cmd[i + 2] == "F9A8D4"
    cmd = _build({"viz_color": ["7DD3FC"]})
    assert cmd[cmd.index("--viz-color") + 1] == "7DD3FC"


def test_viz_color_omitted_when_empty():
    assert "--viz-color" not in _build({"viz_color": ""})


def test_bg_style_solid_forwarded_gradient_omitted():
    assert "--bg-style" not in _build({"bg_style": "gradient"})
    cmd = _build({"bg_style": "solid"})
    assert cmd[cmd.index("--bg-style") + 1] == "solid"


def test_new_design_flags_forwarded():
    cmd = _build({"disc": True, "progress_bar": True, "sub_preview": True,
                  "bg_grad": "0B0F26,241B4D,0D2C44"})
    assert "--disc" in cmd and "--progress-bar" in cmd and "--sub-preview" in cmd
    i = cmd.index("--bg-grad")
    assert cmd[i + 1:i + 4] == ["0B0F26", "241B4D", "0D2C44"]


def test_new_design_flags_omitted_by_default():
    cmd = _build({})
    for flag in ("--disc", "--progress-bar", "--sub-preview", "--bg-grad"):
        assert flag not in cmd


def test_disc_art_forwarded_with_video_bg():
    cmd = _build({"video_bg": "clip.mp4", "disc": True}, bg=["art.jpg"])
    assert cmd[cmd.index("--disc-art") + 1] == "art.jpg"
    assert "--video-bg" in cmd and "--bg" not in cmd


def test_explicit_disc_art_wins_over_bg_list_fallback():
    cmd = _build({"disc": True, "disc_art": "cover.jpg"}, bg=["a.jpg", "b.jpg"])
    assert cmd[cmd.index("--disc-art") + 1] == "cover.jpg"
    assert cmd.count("--disc-art") == 1


def test_explicit_disc_art_wins_with_video_bg_and_no_duplicate_flag():
    cmd = _build({"disc": True, "disc_art": "cover.jpg", "video_bg": "clip.mp4"},
                  bg=["a.jpg", "b.jpg"])
    assert cmd.count("--disc-art") == 1
    assert cmd[cmd.index("--disc-art") + 1] == "cover.jpg"
    assert "--video-bg" in cmd and "--bg" not in cmd


def test_sparkle_flag():
    assert "--sparkle" in _build({"sparkle": True})
    assert "--sparkle" not in _build({})


def test_outro_cta_flag_and_text():
    cmd = _build({"outro_cta": True, "outro_cta_text": "구독 부탁드려요"})
    assert "--outro-cta" in cmd
    assert cmd[cmd.index("--outro-cta-text") + 1] == "구독 부탁드려요"


def test_outro_cta_text_omitted_when_empty():
    cmd = _build({"outro_cta": True})
    assert "--outro-cta" in cmd
    assert "--outro-cta-text" not in cmd
    assert "--outro-cta-text" not in _build({})


def test_disc_bg_style_forwarded_and_off_omitted():
    cmd = _build({"disc": True, "disc_bg_style": "glow"})
    assert cmd[cmd.index("--disc-bg-style") + 1] == "glow"
    assert "--disc-bg-style" not in _build({"disc": True, "disc_bg_style": "off"})
    assert "--disc-bg-style" not in _build({"disc": True})


def test_disc_theme_omitted_by_default():
    # disc_theme 미지정 또는 "classic"(기본값)이면 플래그를 붙이지 않는다 (하위 호환)
    assert "--disc-theme" not in _build({"disc": True})
    assert "--disc-theme" not in _build({"disc": True, "disc_theme": "classic"})
    assert "--disc-ring-text" not in _build({"disc": True})


def test_disc_theme_forwarded():
    cmd = _build({"disc": True, "disc_theme": "lp_vinyl"})
    assert cmd[cmd.index("--disc-theme") + 1] == "lp_vinyl"


def test_disc_ring_text_forwarded():
    cmd = _build({"disc": True, "disc_theme": "text_ring", "disc_ring_text": "hello"})
    assert cmd[cmd.index("--disc-theme") + 1] == "text_ring"
    assert cmd[cmd.index("--disc-ring-text") + 1] == "hello"


def test_disc_ring_text_omitted_when_empty():
    cmd = _build({"disc": True, "disc_ring_text": ""})
    assert "--disc-ring-text" not in cmd


def test_progress_bar_pos_omitted_by_default():
    assert "--progress-bar-pos" not in _build({"progress_bar": True})
    assert "--progress-bar-pos" not in _build({"progress_bar": True, "progress_bar_pos": "bottom"})


def test_progress_bar_pos_forwarded():
    cmd = _build({"progress_bar": True, "progress_bar_pos": "top"})
    assert cmd[cmd.index("--progress-bar-pos") + 1] == "top"


def test_title_caption_forwarded_and_omitted_by_default():
    assert "--title-caption" not in _build({"title": "x"})
    cmd = _build({"title": "x", "title_caption": True})
    assert "--title-caption" in cmd


def test_visual_mode_key_ignored_by_build_command():
    # visual_mode 는 opts 에 존재해도 build_command 가 읽지 않는 키이므로
    # CLI 인자에 영향을 주지 않는다 (프론트가 mode별로 계산한 구체적 옵션 값들이
    # 실제 렌더를 결정한다).
    with_mode = _build({"disc": True, "visual_mode": "music_video"})
    without_mode = _build({"disc": True})
    assert with_mode == without_mode
    assert "visual_mode" not in with_mode
    assert "music_video" not in with_mode


# --- /api/render 엔드포인트: visual_mode 필드 스레딩 테스트 ---
# ffmpeg 는 실제로 실행하지 않는다: _submit 을 동기 실행으로, run_render 를
# 빠른 실패 스텁으로 monkeypatch 해서 jobs.opts 에 저장된 값만 확인한다.

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(os.path.dirname(HERE))
_TEST_AUDIO = os.path.join(ROOT, "examples", "test.mp3")


def _post_render(client, **form_overrides):
    with open(_TEST_AUDIO, "rb") as f:
        files = {"audio": ("test.mp3", f, "audio/mpeg")}
        data = {**form_overrides}
        return client.post("/api/render", files=files, data=data)


def _sync_render_client(monkeypatch):
    """main.app 의 TestClient. /api/render 가 백그라운드 스레드 대신 동기적으로
    돌게 하고, 실제 ffmpeg 대신 즉시 실패하는 스텁을 쓴다 (opts 저장 여부만 확인하면
    충분하므로)."""
    import main as main_module
    from fastapi.testclient import TestClient

    def _fake_submit(fn, jid, *args):
        fn(*args)  # 동기 실행 (스레드풀 대신)

    def _fake_run_render(job_dir, audio, lyrics, bg_list, opts,
                          on_progress=None, on_proc=None):
        return 1, "stub: ffmpeg 실행 안 함", os.path.join(job_dir, "out.mp4")

    monkeypatch.setattr(main_module, "_submit", _fake_submit)
    monkeypatch.setattr(main_module.render, "run_render", _fake_run_render)
    return TestClient(main_module.app), main_module


def test_render_endpoint_defaults_visual_mode_playlist(monkeypatch):
    client, main_module = _sync_render_client(monkeypatch)
    r = _post_render(client)  # visual_mode 미전송 → 기본값 "playlist"
    assert r.status_code == 200
    jid = r.json()["job_id"]
    job = main_module.jobs.get(jid)
    assert job["opts"]["visual_mode"] == "playlist"
    assert job["visual_mode"] == "playlist"


def test_render_endpoint_forwards_visual_mode_music_video(monkeypatch):
    client, main_module = _sync_render_client(monkeypatch)
    r = _post_render(client, visual_mode="music_video")
    assert r.status_code == 200
    jid = r.json()["job_id"]
    job = main_module.jobs.get(jid)
    assert job["opts"]["visual_mode"] == "music_video"
    assert job["visual_mode"] == "music_video"


def test_render_endpoint_forwards_disc_theme_and_ring_text(monkeypatch):
    client, main_module = _sync_render_client(monkeypatch)
    r = _post_render(client, disc_theme="text_ring", disc_ring_text="MY BAND")
    assert r.status_code == 200
    jid = r.json()["job_id"]
    job = main_module.jobs.get(jid)
    assert job["opts"]["disc_theme"] == "text_ring"
    assert job["opts"]["disc_ring_text"] == "MY BAND"


# --- /api/album-cover 엔드포인트 ---

class _FakeImageProvider:
    """네트워크 없이 진짜 파일을 만드는 가짜 이미지 provider."""

    def __init__(self, **kw):
        pass

    def generate(self, prompt, out_path, **opts):
        with open(out_path, "wb") as f:
            f.write(b"fake-png-bytes")
        return out_path


def test_album_cover_endpoint_sets_disc_and_disc_art(monkeypatch):
    client, main_module = _sync_render_client(monkeypatch)

    # 1) 기존 프로젝트(잡) 생성 — 렌더 자체는 스텁이 실패시키지만 assets 는 저장됨
    r = _post_render(client)
    assert r.status_code == 200
    base_jid = r.json()["job_id"]

    # 2) settings / image provider / LLM 호출을 모두 네트워크 없이 가짜로 대체
    monkeypatch.setattr(
        main_module.settings, "get_raw",
        lambda: {"llm_provider": "claude", "llm_model": "claude-sonnet-5",
                 "video_provider": "mock", "video_api_key": ""},
    )
    monkeypatch.setattr(main_module.settings, "get_key", lambda field: "")
    monkeypatch.setattr(
        main_module.video_providers, "get_image_provider",
        lambda name, **kw: _FakeImageProvider(),
    )

    def _fake_prompt(*a, **k):
        raise AssertionError("prompt 를 명시했으므로 LLM 자동생성이 호출되면 안 된다")
    monkeypatch.setattr(main_module.agent, "generate_album_cover_prompt", _fake_prompt)

    r = client.post("/api/album-cover", json={
        "job_id": base_jid, "prompt": "a dreamy sunset, no text",
    })
    assert r.status_code == 200
    njid = r.json()["job_id"]

    job = main_module.jobs.get(njid)
    assert job["opts"]["disc"] is True
    cover_path = job["opts"]["disc_art"]
    assert cover_path and os.path.exists(cover_path)
    with open(cover_path, "rb") as f:
        assert f.read() == b"fake-png-bytes"


def test_album_cover_endpoint_missing_job_404(monkeypatch):
    client, main_module = _sync_render_client(monkeypatch)
    r = client.post("/api/album-cover", json={"job_id": "does-not-exist"})
    assert r.status_code == 404


def test_album_cover_endpoint_no_key_without_mock_fails(monkeypatch):
    client, main_module = _sync_render_client(monkeypatch)
    r = _post_render(client)
    base_jid = r.json()["job_id"]

    monkeypatch.setattr(
        main_module.settings, "get_raw",
        lambda: {"llm_provider": "claude", "llm_model": "claude-sonnet-5",
                 "video_provider": "replicate", "video_api_key": ""},
    )
    monkeypatch.setattr(main_module.settings, "get_key", lambda field: "")

    r = client.post("/api/album-cover", json={"job_id": base_jid})
    assert r.status_code == 400


def test_render_endpoint_saves_uploaded_disc_art(monkeypatch):
    client, main_module = _sync_render_client(monkeypatch)
    cover_bytes = b"fake-cover-art-bytes"
    with open(_TEST_AUDIO, "rb") as f:
        files = {
            "audio": ("test.mp3", f, "audio/mpeg"),
            "disc_art": ("cover.jpg", cover_bytes, "image/jpeg"),
        }
        r = client.post("/api/render", files=files, data={"disc": "true"})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    job = main_module.jobs.get(jid)
    disc_art_path = job["opts"]["disc_art"]
    assert disc_art_path is not None
    assert os.path.exists(disc_art_path)
    with open(disc_art_path, "rb") as f:
        assert f.read() == cover_bytes
