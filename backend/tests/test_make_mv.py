"""렌더 엔진의 순수 함수(가사 파싱/시간/레이아웃) 단위 테스트."""
import make_mv as mv


def test_parse_time_forms():
    assert mv.parse_time("65") == 65.0
    assert mv.parse_time("1:05") == 65.0
    assert mv.parse_time("1:05.5") == 65.5
    assert mv.parse_time("1:00:00") == 3600.0


def test_even_distribute_covers_duration():
    lines = ["a", "b", "c", "d"]
    cues = mv.even_distribute(lines, 8.0)
    assert len(cues) == 4
    assert cues[0][0] == 0.0
    # 마지막 cue 끝은 곡 길이와 일치
    assert abs(cues[-1][1] - 8.0) < 1e-6
    # 텍스트 순서 보존
    assert [c[2] for c in cues] == lines


def test_even_distribute_with_intro_outro():
    cues = mv.even_distribute(["a", "b"], 10.0, intro=2.0, outro=2.0)
    assert cues[0][0] == 2.0
    assert abs(cues[-1][1] - 8.0) < 1e-6


def test_parse_lrc_and_cues(tmp_path):
    p = tmp_path / "x.lrc"
    p.write_text("[00:01.00]first\n[00:03.50]second\nnot a line\n", encoding="utf-8")
    items = mv.parse_lrc(str(p))
    assert items == [(1.0, "first"), (3.5, "second")]
    cues = mv.lrc_to_cues(items, duration=10.0)
    assert cues[0] == (1.0, 3.5, "first")
    assert cues[1] == (3.5, 10.0, "second")


def test_slice_cues_for_clip_shifts_and_filters():
    cues = [(0, 2, "a"), (2, 4, "b"), (4, 6, "c")]
    out = mv.slice_cues_for_clip(cues, start=2.0, length=2.0)
    # [2,4] 구간만 남고 시작이 0으로 시프트
    assert out == [(0.0, 2.0, "b")]


def test_get_layout_dimensions():
    assert mv.get_layout(False)["W"] == 1920
    assert mv.get_layout(True)["W"] == 1080
    assert mv.get_layout(True)["H"] == 1920


def test_fmt_ass_time():
    assert mv.fmt_ass_time(3661.25).startswith("1:01:01")


def test_ass_escape_braces():
    assert "{" not in mv.ass_escape("a{b}c")


def test_hex_to_ass_bgr_order():
    assert mv.hex_to_ass("FFFFFF") == "&H00FFFFFF"
    assert mv.hex_to_ass("FFD700") == "&H0000D7FF"   # 골드 RRGGBB -> BGR
    assert mv.hex_to_ass("#FF0000") == "&H000000FF"   # # 접두 허용, 빨강
    assert mv.hex_to_ass("bad") == "&H00FFFFFF"       # 잘못된 값 -> 흰색


def test_parse_time_invalid_raises():
    import pytest
    with pytest.raises(ValueError):
        mv.parse_time("abc")


def test_karaoke_text_distributes_duration():
    t = mv.karaoke_text("abcd", 2.0)  # 2초 / 4글자 -> 글자당 50cs
    assert t.count("\\kf") == 4
    assert "{\\kf50}a" in t


def test_loudnorm_filter_single_pass():
    assert mv.loudnorm_filter("x.mp3", two_pass=False) == "loudnorm=I=-14:TP=-1.5:LRA=11"


def test_loudnorm_filter_twopass_fallback_on_bad_input():
    # 측정 실패(없는 파일) 시 단일 패스 문자열로 폴백
    assert mv.loudnorm_filter("nonexistent.wav", two_pass=True) == "loudnorm=I=-14:TP=-1.5:LRA=11"


def test_draw_font_spec_quotes_fontfile():
    spec = mv.draw_font_spec()
    if mv.DRAW_FONTFILE:
        # 콜론 포함 경로는 작은따옴표+이스케이프로 감싸야 filtergraph 파싱됨
        assert spec.startswith("fontfile='") and spec.endswith("'")
        if ":" in mv.DRAW_FONTFILE:
            assert "\\:" in spec
    else:
        assert spec.startswith("font=")


def test_read_txt_strips_bom(tmp_path):
    p = tmp_path / "l.txt"
    p.write_bytes("﻿첫줄\n둘째\n".encode("utf-8"))
    lines = mv.read_txt_lines(str(p))
    assert lines[0] == "첫줄"  # BOM 제거됨


def test_norm_hex_forms():
    assert mv.norm_hex("#7dd3fc") == "7DD3FC"
    assert mv.norm_hex("0xF0ABFC") == "F0ABFC"
    assert mv.norm_hex("nope", "AABBCC") == "AABBCC"


def test_derive_bg_grad_returns_three_hex():
    cols = mv.derive_bg_grad("0x0a0a14")
    assert len(cols) == 3
    for c in cols:
        assert len(c) == 6 and int(c, 16) >= 0
    # 색명 등 파싱 불가 입력은 기본 팔레트로
    assert mv.derive_bg_grad("black") == mv.DEFAULT_BG_GRAD


def test_build_viz_waves_gradient_dual_glow():
    lay = mv.get_layout(False)
    parts, labels = mv.build_viz("1:a", lay, "waves")
    # 겉광 -> 속광 -> 본체 순으로 겹침
    assert labels == ["[vglow2]", "[vglow1]", "[vsharp]"]
    joined = ";".join(parts)
    assert "gradients=" in joined and "alphamerge" in joined and "gblur" in joined
    # 2배 슈퍼샘플링 후 lanczos 다운스케일
    assert f"s={lay['W'] * 2}x{lay['viz_h'] * 2}" in parts[0]
    assert "flags=lanczos" in joined


def test_build_viz_bars_segmented():
    lay = mv.get_layout(False)
    parts, labels = mv.build_viz("1:a", lay, "bars")
    joined = ";".join(parts)
    assert "drawgrid" in joined  # 막대 사이 갭
    assert labels == ["[vglow2]", "[vglow1]", "[vsharp]"]


def test_build_viz_line_gradient_glow():
    lay = mv.get_layout(False)
    parts, labels = mv.build_viz("1:a", lay, "line")
    assert labels == ["[lglow]", "[lsharp]"]
    assert "p2p" in parts[0]


def test_build_bg_gradient_default_and_solid():
    lay = mv.get_layout(False)
    _, parts, lbl, n = mv.build_bg(None, lay, 10.0, True, "0x0a0a14")
    assert lbl == "[bg]" and n == 0
    assert "gradients=" in parts[0]
    _, parts, _, _ = mv.build_bg(None, lay, 10.0, True, "0x0a0a14", bg_style="solid")
    assert parts[0].startswith("color=c=0x0a0a14")


def test_write_ass_fade_and_bundled_bold(tmp_path):
    lay = mv.get_layout(False)
    p = tmp_path / "s.ass"
    mv.write_ass([(0.0, 2.0, "안녕")], str(p), lay, font="Jua")
    txt = p.read_text(encoding="utf-8")
    assert "\\fad(200,260)" in txt
    # 동봉 라운드 폰트는 합성 볼드 없이 (Bold=0)
    assert ",0,0,0,0,100,100," in txt
    mv.write_ass([(0.0, 2.0, "안녕")], str(p), lay, font="Jua", fade=False)
    assert "\\fad" not in p.read_text(encoding="utf-8")


def test_write_ass_preview_next_line(tmp_path):
    lay = mv.get_layout(False)
    p = tmp_path / "s.ass"
    cues = [(0.0, 2.0, "첫 줄"), (2.0, 4.0, "둘째 줄")]
    mv.write_ass(cues, str(p), lay, preview=True)
    txt = p.read_text(encoding="utf-8")
    assert "Style: Next," in txt
    # 첫 줄이 나오는 동안 둘째 줄이 Next 스타일로 미리 보임
    assert "Next,,0,0,0," in txt and txt.count("Dialogue:") == 3
    # middle 정렬에선 미리보기 생략
    mv.write_ass(cues, str(p), lay, preview=True, pos="middle")
    assert "Style: Next," not in p.read_text(encoding="utf-8")


def test_disc_diameter_even_and_orientation():
    d_land = mv.disc_diameter(mv.get_layout(False))
    d_short = mv.disc_diameter(mv.get_layout(True))
    assert d_land % 2 == 0 and d_short % 2 == 0
    assert d_land == int(1080 * 0.42) - (int(1080 * 0.42) % 2)
    assert d_short == int(1080 * 0.55) - (int(1080 * 0.55) % 2)


def test_sparkle_params_deterministic_and_in_range():
    a = mv.sparkle_params(0)
    b = mv.sparkle_params(0)
    assert a == b  # 같은 인덱스는 항상 같은 파라미터(재현 가능)
    seen = {mv.sparkle_params(i) for i in range(mv.SPARKLE_COUNT)}
    assert len(seen) == mv.SPARKLE_COUNT  # 파티클마다 서로 다른 파라미터
    for _, _, sx, sy, _, period, size in seen:
        assert sx > 0 and sy > 0  # 항상 오른쪽/위쪽으로 표류
        assert period > 0
        assert size > 0


def test_build_bg_glow_applies_blur_and_saturation_not_brightness():
    _, parts, label, _ = mv.build_bg(
        ["bg1.jpg"], mv.get_layout(False), 8.0, True, "0x0a0a14",
        disc_bg_style="glow")
    joined = ";".join(parts)
    assert "gblur=sigma=42" in joined
    assert "eq=saturation=1.4" in joined
    # 어두운 앨범아트를 더 죽이지 않도록 밝기(brightness)는 건드리지 않는다
    assert "brightness" not in joined
    assert label == "[bg]"


def test_build_bg_off_style_has_no_blur():
    _, parts, label, _ = mv.build_bg(
        ["bg1.jpg"], mv.get_layout(False), 8.0, True, "0x0a0a14",
        disc_bg_style="off")
    joined = ";".join(parts)
    assert "gblur" not in joined
    assert label == "[bg]"


def test_build_sparkle_chains_all_particles():
    parts, cur = mv.build_sparkle("[in]", 1920, 1080)
    assert len(parts) == mv.SPARKLE_COUNT
    assert cur == f"[vspk{mv.SPARKLE_COUNT - 1}]"
    assert parts[0].startswith("[in]drawtext=")
    assert all("alpha=" in p and "text='♪'" in p for p in parts)
