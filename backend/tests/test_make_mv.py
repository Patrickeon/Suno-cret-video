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


def test_progress_bar_geometry_bottom_vs_top():
    W, H = 1920, 1080
    mx_b, bw_b, bh_b, y_b = mv.progress_bar_geometry(W, H, 1.0, "bottom")
    mx_t, bw_t, bh_t, y_t = mv.progress_bar_geometry(W, H, 1.0, "top")
    # 좌우 여백/두께/폭은 위치와 무관하게 동일
    assert mx_b == mx_t and bw_b == bw_t and bh_b == bh_t
    # 여백을 둬서 양 끝 둥근 캡이 화면 밖으로 잘리지 않도록 함
    assert mx_b > 0
    assert bw_b == W - 2 * mx_b
    # top 은 화면 상단 쪽, bottom 은 화면 하단 쪽에 위치
    assert y_t < H / 2
    assert y_b > H / 2
    assert y_b + bh_b <= H  # 하단에 붙어도 프레임을 벗어나지 않음


def test_progress_bar_geometry_default_pos_is_bottom():
    # --progress-bar-pos 기본값(bottom)과 동일한 결과여야 한다
    W, H = 1080, 1920
    assert mv.progress_bar_geometry(W, H, 1.0) == mv.progress_bar_geometry(W, H, 1.0, "bottom")


def test_pill_alpha_expr_static_track_has_no_time_var():
    expr = mv.pill_alpha_expr(400, 10, 0.3)
    assert "hypot" in expr
    assert "T" not in expr  # 트랙(고정 폭)엔 시간 변수가 없어야 함
    assert expr.startswith(str(round(255 * 0.3)))


def test_pill_alpha_expr_with_fill_expr_gates_on_x_and_time():
    fill_expr = "400*clip(T/10.000,0,1)"
    expr = mv.pill_alpha_expr(400, 10, 0.9, fill_expr=fill_expr)
    assert fill_expr in expr
    assert "lte(X," + fill_expr + ")" in expr
    assert "hypot" in expr


def test_title_caption_geometry_disc_active_positions_below_disc():
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        True, D=400, cy=324, H=1080, scale=1.0)
    assert ttl_y > 324 + 200  # 디스크 중심+반지름보다 아래
    assert ttl_fs > art_fs  # 제목이 아티스트보다 큼(더 굵게 보이도록)
    assert art_gap > 0


def test_title_caption_geometry_disc_inactive_positions_near_top():
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        False, D=0, cy=0, H=1080, scale=1.0)
    assert ttl_y < 1080 / 4  # 화면 상단 근처 (기본 하단 자막과 안 겹치게)


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


# ---------- 레코드 모드: 테마 (classic / lp_vinyl / text_ring) ----------

def test_disc_theme_arg_default_and_choices(monkeypatch, capsys):
    import pytest
    monkeypatch.setattr("sys.argv", ["make_mv.py", "--help"])
    with pytest.raises(SystemExit):
        mv.main()
    out = capsys.readouterr().out
    assert "--disc-theme" in out
    assert ("classic" in out and "lp_vinyl" in out and "text_ring" in out
            and "square_spin" in out)
    assert "--disc-ring-text" in out


def test_progress_bar_pos_arg_default_and_choices(monkeypatch, capsys):
    import pytest
    monkeypatch.setattr("sys.argv", ["make_mv.py", "--help"])
    with pytest.raises(SystemExit):
        mv.main()
    out = capsys.readouterr().out
    assert "--progress-bar-pos" in out
    # argparse --help 는 choices 를 {top,bottom} 형태로 보여준다
    assert "top" in out and "bottom" in out


def test_title_caption_cli_flag_declared_and_defaults_false():
    # main() 안에서 argparse.ArgumentParser 가 직접 구성되며 별도 팩토리 함수가
    # 없으므로, --keep-meta-lines 테스트와 동일하게 소스 레벨로 검증한다.
    import inspect
    src = inspect.getsource(mv.main)
    assert '"--title-caption"' in src
    assert 'store_true' in src.split('"--title-caption"')[1][:80]


def test_square_spin_disc_theme_uses_square_png_not_circular_mask(tmp_path):
    """main() 의 프리패스 디스패치가 square_spin 일 때 make_square_png 를 쓰는지
    (마스킹/링 없는 단순 크롭) 소스 레벨로 확인 — make_disc_png(원형 마스킹)와
    섞이지 않아야 한다."""
    import inspect
    src = inspect.getsource(mv.main)
    branch = src.split('elif args.disc_theme == "square_spin":')[1].split("else:")[0]
    assert "make_square_png(" in branch
    assert "make_disc_png(" not in branch


def test_make_vinyl_png_generates_file(tmp_path):
    out = tmp_path / "vinyl.png"
    mv.make_vinyl_png(str(out), 300, "7DD3FC")
    assert out.exists() and out.stat().st_size > 0


def test_make_square_png_crops_without_mask(tmp_path):
    src = tmp_path / "src.png"
    mv.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", "color=c=red:s=64x40:r=1",
            "-frames:v", "1", str(src)])
    out = tmp_path / "square.png"
    mv.make_square_png(str(src), str(out), 50)
    assert out.exists() and out.stat().st_size > 0


def test_default_ring_text_prefers_title_artist():
    assert mv.default_ring_text("My Friend", "Mark Lee") == "My Friend - Mark Lee - "
    assert mv.default_ring_text("My Friend", "") == "My Friend - "
    assert mv.default_ring_text("", "Mark Lee") == "Mark Lee - "
    assert mv.default_ring_text("", "") == mv._DEFAULT_RING_PHRASE


def test_make_ring_text_png_missing_pillow_exits(tmp_path, monkeypatch):
    import pytest
    import sys
    # PIL 미설치 환경을 흉내내 opt-in 의존성 에러 경로를 검증 (실제 렌더는 안 함)
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(SystemExit):
        mv.make_ring_text_png(str(tmp_path / "ring.png"), 200, "TEXT", None)


def test_make_ring_text_png_generates_file_when_pillow_available(tmp_path):
    import pytest
    pytest.importorskip("PIL")  # Pillow 미설치 환경에선 건너뜀 (opt-in 의존성)
    out = tmp_path / "ring.png"
    mv.make_ring_text_png(str(out), 300, "TEST RING TEXT",
                          mv.bundled_font_file(mv.SUB_FONT))
    assert out.exists() and out.stat().st_size > 0


# --- SUNO 프롬프트 형식(섹션 태그/연출 지시문) 필터링 -----------------------------

SUNO_STYLE_LYRICS = """[Intro]
(Boom—Clap! Boom—Clap!)
(Deep male solo, low and gritty)
There once was a line…
Huh!

[Verse 1]
(Chanting, bouncy)
태어날 때부터 발목을 잡는 무거운 밑선 (Hey!)
손가락 끝 시선이 날 찍어누르는 차가운 시선 (Ho!)
너의 기준, 나의 기준—영원히 안 닿는 평행선
맞추려 애써도 우린 궤도가 다른 위성 (Ha!)

[Chorus]
(Big gang vocals, super catchy)
선을 긋고! (Hey!) 선을 넘고! (Ho!) 다시 선 위에 서! (Ha!)
내 이름으로 그려가, 흔들려도 중심은 "나"!
거친 파도 덮쳐와도—철갑 두른 거북선!
천지가 뒤집혀도 꺾이지 않아, 내 중심선!
(Hey! Hey! Hey! Hey!)
"""


def test_is_section_tag_line_matches_bracket_only():
    assert mv.is_section_tag_line("[Verse 1]")
    assert mv.is_section_tag_line("  [Chorus]  ")
    assert mv.is_section_tag_line("[Pre-Chorus]")
    assert not mv.is_section_tag_line("Huh!")
    assert not mv.is_section_tag_line("(Chanting, bouncy)")


def test_is_stage_direction_line_matches_paren_only():
    assert mv.is_stage_direction_line("(Chanting, bouncy)")
    assert mv.is_stage_direction_line("(Boom—Clap! Boom—Clap!)")
    assert mv.is_stage_direction_line("(Hey! Hey! Hey! Hey!)")
    assert not mv.is_stage_direction_line("[Verse 1]")
    assert not mv.is_stage_direction_line("Huh!")


def test_real_lyric_lines_are_neither_tag_nor_direction():
    # 인라인 애드립이 붙은 실제 가사 줄은 태그도 연출 지시문도 아니다 (그대로 유지되어야 함)
    line1 = "태어날 때부터 발목을 잡는 무거운 밑선 (Hey!)"
    line2 = '선을 긋고! (Hey!) 선을 넘고! (Ho!) 다시 선 위에 서! (Ha!)'
    for line in (line1, line2, "Huh!"):
        assert not mv.is_section_tag_line(line)
        assert not mv.is_stage_direction_line(line)


def test_filter_lyric_lines_drops_tags_and_directions_when_requested():
    lines = [ln.strip() for ln in SUNO_STYLE_LYRICS.splitlines() if ln.strip()]
    kept, dropped = mv.filter_lyric_lines(lines, drop_stage_directions=True)

    # 섹션 태그는 전부 제외
    assert not any(mv.is_section_tag_line(ln) for ln in kept)
    assert "[Intro]" in dropped and "[Verse 1]" in dropped and "[Chorus]" in dropped

    # 괄호로만 이루어진 연출 지시문 줄도 전부 제외
    assert "(Boom—Clap! Boom—Clap!)" in dropped
    assert "(Deep male solo, low and gritty)" in dropped
    assert "(Chanting, bouncy)" in dropped
    assert "(Big gang vocals, super catchy)" in dropped
    assert "(Hey! Hey! Hey! Hey!)" in dropped

    # 인라인 애드립이 붙은 실제 가사 줄은 원문 그대로 보존, 순서도 유지
    assert "태어날 때부터 발목을 잡는 무거운 밑선 (Hey!)" in kept
    assert "선을 긋고! (Hey!) 선을 넘고! (Ho!) 다시 선 위에 서! (Ha!)" in kept
    assert "Huh!" in kept
    assert kept == [ln for ln in lines
                     if not mv.is_section_tag_line(ln) and not mv.is_stage_direction_line(ln)]


def test_filter_lyric_lines_keeps_stage_directions_when_disabled():
    lines = [ln.strip() for ln in SUNO_STYLE_LYRICS.splitlines() if ln.strip()]
    kept, dropped = mv.filter_lyric_lines(lines, drop_stage_directions=False)

    # 섹션 태그만 제외
    assert all(not mv.is_section_tag_line(ln) for ln in kept)
    assert "[Verse 1]" in dropped and "[Chorus]" not in kept

    # 연출 지시문 전용 줄은 유지된다 (오디오 정렬이 실제 발화 여부를 판단)
    assert "(Hey! Hey! Hey! Hey!)" in kept
    assert "(Chanting, bouncy)" in kept
    assert "(Boom—Clap! Boom—Clap!)" in kept


def test_keep_meta_lines_cli_flag_defaults_false():
    # main() 안에서 argparse.ArgumentParser가 직접 구성되며 별도 팩토리 함수가
    # 없으므로, 플래그 선언과 기본값을 소스 레벨로 검증한다.
    import inspect
    src = inspect.getsource(mv.main)
    assert '"--keep-meta-lines"' in src
    assert 'action="store_true"' in src.split('"--keep-meta-lines"')[1].split("\n")[0] \
        or 'store_true' in src.split('"--keep-meta-lines"')[1][:80]


def test_suno_example_reduces_to_real_lyric_lines_only():
    lines = [ln.strip() for ln in SUNO_STYLE_LYRICS.splitlines() if ln.strip()]
    kept, dropped = mv.filter_lyric_lines(lines, drop_stage_directions=True)
    expected = [
        "There once was a line…",
        "Huh!",
        "태어날 때부터 발목을 잡는 무거운 밑선 (Hey!)",
        "손가락 끝 시선이 날 찍어누르는 차가운 시선 (Ho!)",
        "너의 기준, 나의 기준—영원히 안 닿는 평행선",
        "맞추려 애써도 우린 궤도가 다른 위성 (Ha!)",
        '선을 긋고! (Hey!) 선을 넘고! (Ho!) 다시 선 위에 서! (Ha!)',
        '내 이름으로 그려가, 흔들려도 중심은 "나"!',
        "거친 파도 덮쳐와도—철갑 두른 거북선!",
        "천지가 뒤집혀도 꺾이지 않아, 내 중심선!",
    ]
    assert kept == expected
    assert len(dropped) == len(lines) - len(expected)
