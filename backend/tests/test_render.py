"""render.build_command 의 옵션→CLI 매핑 테스트 (ffmpeg 실행 없음)."""
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
