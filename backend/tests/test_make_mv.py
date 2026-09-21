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


def test_lp_vinyl_size_scale_only_affects_lp_vinyl_branches():
    """disc_diameter() 는 classic/text_ring/square_spin 이 공유하므로 절대
    바꾸면 안 된다 — 대신 LP_VINYL_SIZE_SCALE 은 lp_vinyl 전용 분기(main() 프리
    패스, render() 오버레이)에서만 D 에 곱해져야 한다(소스 레벨 확인)."""
    import inspect
    main_src = inspect.getsource(mv.main)
    render_src = inspect.getsource(mv.render)

    main_branch = main_src.split('if args.disc_theme == "lp_vinyl":')[1].split(
        'elif args.disc_theme == "text_ring":')[0]
    assert "LP_VINYL_SIZE_SCALE" in main_branch

    render_branch = render_src.split(
        'elif disc_theme == "lp_vinyl" and vinyl_png and cover_png:')[1].split(
        'elif disc_theme == "text_ring"')[0]
    assert "LP_VINYL_SIZE_SCALE" in render_branch

    # text_ring/square_spin/classic 분기엔 LP_VINYL_SIZE_SCALE 이 전혀 등장하면 안 됨
    text_ring_main_branch = main_src.split('elif args.disc_theme == "text_ring":')[1].split(
        'elif args.disc_theme == "square_spin":')[0]
    assert "LP_VINYL_SIZE_SCALE" not in text_ring_main_branch

    text_ring_render_branch = render_src.split('elif disc_theme == "text_ring"')[1].split(
        "# 자막 burn-in")[0]
    assert "LP_VINYL_SIZE_SCALE" not in text_ring_render_branch


def test_lp_vinyl_size_scale_enlarges_cover_relative_to_disc_diameter():
    # 레퍼런스(sample/palylist_sample2.png) 실측: 커버 높이/프레임 높이 ≈0.64,
    # disc_diameter() 가 가로형에 주는 값은 ≈0.42 — LP_VINYL_SIZE_SCALE 은 그
    # 간극을 메우는 배율(>1)이어야 한다.
    import pytest
    assert mv.LP_VINYL_SIZE_SCALE > 1.0
    lay = mv.get_layout(False)
    D = mv.disc_diameter(lay)
    D_lp = int(D * mv.LP_VINYL_SIZE_SCALE)
    D_lp -= D_lp % 2
    ratio_before = D / lay["H"]
    ratio_after = D_lp / lay["H"]
    assert ratio_before == pytest.approx(0.419, abs=0.01)
    assert ratio_after == pytest.approx(0.63, abs=0.03)


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


def test_progress_bar_geometry_is_narrow_and_centered():
    # 디자인 레퍼런스(sample/playlist_sample1.png)를 PIL 로 실측하면
    # bar_width/image_width ≈0.26 인 가운데 정렬 알약형 바다. 예전 공식
    # (margin_x=70px 고정)은 1920 폭 기준 bar_w/W ≈0.93(거의 풀폭)이었다.
    for W, H in [(1920, 1080), (1080, 1920), (3840, 2160)]:
        margin_x, bar_w, bar_h, _ = mv.progress_bar_geometry(W, H, 1.0)
        ratio = bar_w / W
        assert 0.20 <= ratio <= 0.35, (W, H, ratio)
        # 좌우 여백이 같아야 가운데 정렬(margin_x*2 + bar_w == W, 반올림 오차 허용)
        assert abs((margin_x * 2 + bar_w) - W) <= 1


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


def test_subtitle_zone_y_bottom_matches_margin_v():
    lay = mv.get_layout(shorts=False, scale=1.0)
    zone_top, zone_bottom = mv.subtitle_zone_y(lay, sub_pos="bottom")
    # Alignment=2 의 MarginV 는 화면 하단에서 잰다 -> zone_bottom == H - margin_v
    assert zone_bottom == lay["H"] - lay["margin_v"]
    assert zone_top < zone_bottom


def test_title_caption_geometry_disc_active_avoids_overlapping_subtitle_zone():
    # 실제 버그 재현 치수(1280x720, --preview-secs 로 스케일된 레이아웃)에서
    # 자막 안전영역과 겹치던 케이스 -> 캡션이 자막 아래로 내려가야 한다.
    lay = mv.get_layout(shorts=False, scale=2 / 3)
    D = mv.disc_diameter(lay)
    cy = int(lay["H"] * 0.36)
    sub_zone = mv.subtitle_zone_y(lay, sub_pos="bottom")
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        True, D, cy, lay["H"], scale=2 / 3, pos="auto", sub_zone=sub_zone)
    cap_bottom = ttl_y + art_gap + art_fs
    sub_top, sub_bottom = sub_zone
    # 캡션 블록(제목~아티스트)이 자막 안전영역과 겹치면 안 된다
    assert not (ttl_y < sub_bottom and cap_bottom > sub_top)
    # 디스크 바로 아래가 아니라 자막 영역보다 아래로 내려갔어야 한다
    assert ttl_y >= sub_bottom


def test_title_caption_geometry_no_sub_zone_keeps_legacy_placement():
    # sub_zone 을 주지 않으면(기존 호출부와 하위호환) 기존 동작과 동일하게
    # 디스크 바로 아래에 그대로 배치된다. 여백은 D 의 0.17배(레퍼런스
    # sample/playlist_sample1.png 실측: 커버-캡션 간격 58px / D_ref 346px).
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        True, D=400, cy=324, H=1080, scale=1.0, sub_zone=None)
    assert ttl_y == 324 + 200 + int(round(400 * 0.17))


def test_title_caption_geometry_small_disc_unaffected_by_sub_zone():
    # 디스크가 작아 자막 영역과 애초에 겹치지 않는 경우, sub_zone 을 줘도
    # 기존 '디스크 바로 아래' 위치가 그대로 유지돼야 한다(회귀 방지)
    lay = mv.get_layout(shorts=False, scale=1.0)
    sub_zone = mv.subtitle_zone_y(lay, sub_pos="bottom")
    D, cy = 100, 200
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        True, D, cy, lay["H"], scale=1.0, pos="auto", sub_zone=sub_zone)
    assert ttl_y == cy + D // 2 + int(round(D * 0.17))


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


def test_make_vinyl_png_with_art_src_embeds_label_not_flat_accent(tmp_path):
    """디자인 레퍼런스(sample/palylist_sample2.png)처럼 라벨이 flat accent 색이
    아니라 실제 앨범아트를 반영해야 한다: art_src 를 주면 라벨 영역 픽셀이
    art_src 없이 생성한 flat-accent 버전과 달라야 한다."""
    import pytest
    pytest.importorskip("PIL")
    from PIL import Image

    art = tmp_path / "art.png"
    mv.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", "color=c=0x0000FF:s=300x300:r=1",
            "-frames:v", "1", str(art)])

    flat = tmp_path / "vinyl_flat.png"
    mv.make_vinyl_png(str(flat), 300, "FF0000")

    with_art = tmp_path / "vinyl_art.png"
    mv.make_vinyl_png(str(with_art), 300, "FF0000", art_src=str(art))

    assert with_art.exists() and with_art.stat().st_size > 0
    assert not (tmp_path / "_vinyl_art_base.png").exists()  # 임시 파일 정리됨

    D = 300
    c = D // 2
    label_r = D * 0.22
    # 홀은 피하고 라벨 링 안쪽의 한 점을 확인(중심에서 label_r/2 만큼 오프셋)
    probe = (c + int(label_r / 2), c)
    flat_px = Image.open(flat).convert("RGB").getpixel(probe)
    art_px = Image.open(with_art).convert("RGB").getpixel(probe)
    assert art_px != flat_px
    # art_src 가 순수 파랑이었으니 art 버전은 red accent(flat_px)보다 파랑에 가까워야 함
    assert art_px[2] > art_px[0]


def test_make_vinyl_png_no_art_src_falls_back_to_flat_accent(tmp_path):
    """art_src 를 주지 않으면(폴백) 이전과 동일하게 라벨이 flat accent 색이어야
    하며, 3단 합성 임시 파일도 생기지 않아야 한다(단일 geq 패스로 처리)."""
    out = tmp_path / "vinyl.png"
    mv.make_vinyl_png(str(out), 300, "7DD3FC")
    assert out.exists()
    assert not any(tmp_path.glob("_vinyl_*"))


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


# ---------- 앨범 커버 드롭섀도우 (add_square_shadow) ----------

def test_add_square_shadow_returns_new_label_and_appends_blur_chain():
    parts = []
    new_label = mv.add_square_shadow(parts, "[cur]", 300, 100, 50, 30, "x")
    assert new_label != "[cur]"
    assert new_label.startswith("[") and new_label.endswith("]")
    joined = ";".join(parts)
    assert "gblur=sigma=" in joined
    assert "color=c=black" in joined
    # 캔버스 소스와 최종 합성 오버레이 두 파트가 순서대로 추가돼야 한다
    assert len(parts) == 2
    assert new_label in parts[1]


def test_add_square_shadow_offsets_by_pad_and_slight_downward_bias():
    # 레퍼런스(sample/playlist_sample1.png) 실측: 위쪽은 안팎 밝기 차이가
    # 거의 없고(89 vs 91) 아래쪽만 뚜렷이 어두워진다(67 -> 100px 아래 192).
    # offset_y == pad 로 두면 섀도우의 흐려진 윗부분이 정확히 커버 뒤로
    # 완전히 숨고(위쪽 노출 0) 아랫부분만 2*pad 만큼 드러난다 — 매직 넘버가
    # 아니라 pad 자체에서 유도된 값이어야 한다.
    parts = []
    size, x, y = 300, 100, 50
    mv.add_square_shadow(parts, "[cur]", size, x, y, 30, "x")
    sigma = max(4, int(round(size * 0.035)))
    pad = max(sigma * 3, int(round(size * 0.10)))
    offset_y = pad
    overlay_part = parts[1]
    assert f"overlay={x - pad}:{y - pad + offset_y}" in overlay_part
    # sy == y : 섀도우 캔버스 상단이 커버 상단과 정확히 겹쳐(=위쪽 비노출)
    assert f"overlay={x - pad}:{y}" in overlay_part


def test_add_square_shadow_pad_large_enough_to_avoid_clipping_blur():
    # 회귀 방지: 초기 구현은 pad(size*0.06)가 sigma(size*0.035)의 ~1.6배뿐이라
    # gblur 가 캔버스 경계에서 잘려(하드 클립) 15~20px 만에 사라지는 버그가
    # 있었다(실제 렌더 프레임을 PIL 로 재측정해 발견). pad 는 sigma 의 최소
    # 3배는 되어야 가우시안 낙차가 캔버스 안에서 자연스럽게 다 그려진다.
    parts = []
    size = 300
    mv.add_square_shadow(parts, "[cur]", size, 0, 0, 30, "x")
    sigma = max(4, int(round(size * 0.035)))
    pad = max(sigma * 3, int(round(size * 0.10)))
    assert pad >= sigma * 3
    canvas_line = parts[0]
    assert f"s={size + pad * 2}x{size + pad * 2}" in canvas_line


def test_add_square_shadow_unique_labels_avoid_collisions():
    parts = []
    mv.add_square_shadow(parts, "[cur]", 300, 0, 0, 30, "lp")
    mv.add_square_shadow(parts, "[cur]", 300, 0, 0, 30, "tr")
    joined = ";".join(parts)
    assert "shsrc_lp" in joined and "shsrc_tr" in joined
    assert "vsh_lp" in joined and "vsh_tr" in joined


def test_lp_vinyl_and_text_ring_branches_apply_cover_shadow_before_overlay():
    """레코드 모드의 정사각 커버(lp_vinyl/text_ring) 는 실제 커버를 올리기 전에
    add_square_shadow() 로 섀도우를 먼저 합성해야 한다(classic 은 원형 마스킹에
    이미 자체 엣지 처리가 있어 범위 밖 — 이 테스트는 정사각 커버 두 테마만 확인)."""
    import inspect
    render_src = inspect.getsource(mv.render)
    lp_branch = render_src.split(
        'elif disc_theme == "lp_vinyl" and vinyl_png and cover_png:')[1].split(
        'elif disc_theme == "text_ring"')[0]
    assert "add_square_shadow(" in lp_branch
    assert lp_branch.index("add_square_shadow(") < lp_branch.index("[coverfg]")

    text_ring_branch = render_src.split('elif disc_theme == "text_ring"')[1].split(
        "# 자막 burn-in")[0]
    assert "add_square_shadow(" in text_ring_branch
    assert text_ring_branch.index("add_square_shadow(") < text_ring_branch.index("[coverfg]")


# ---------- 진행바 손잡이(handle) ----------

def test_progress_bar_block_draws_time_driven_circular_handle():
    """진행바 필과 별개로, 재생 위치에 원형 손잡이가 t/duration 비율로 슬라이드
    해야 한다(레퍼런스 sample/playlist_sample1.png 실측: 손잡이 지름 ≈ 트랙
    높이의 2배, 흰색, overlay eval=frame 로 매 프레임 위치 갱신)."""
    import inspect
    render_src = inspect.getsource(mv.render)
    pb_block = render_src.split("if progress_bar and duration:")[1].split(
        "outro_cta and duration")[0]
    assert "pbhandle" in pb_block
    assert "eval=frame" in pb_block
    assert "bar_h * 2.0" in pb_block
    # 핸들은 필의 색(accent)이 아니라 트랙과 같은 흰색이어야 한다(핸들 캔버스
    # 생성부는 color=c=white 로 시작해 [pbhandle] 라벨로 끝나는 하나의 f-string
    # 체인 — 소스상 여러 줄로 나뉘므로 개행/공백을 제거하고, [pbhandle] 라벨
    # 바로 앞쪽 구간에서 가장 가까운 color=c=white 를 찾아 accent 가 없는지 본다).
    collapsed = pb_block.replace("\n", "").replace(" ", "")
    handle_pos = collapsed.index("[pbhandle]")
    preceding = collapsed[:handle_pos]
    handle_src_start = preceding.rindex("color=c=white")
    handle_src_region = collapsed[handle_src_start:handle_pos]
    assert "accent" not in handle_src_region


def test_progress_bar_handle_diameter_matches_measured_ratio():
    # 순수 함수 조합으로 실제 render() 와 동일한 계산을 재현해 손잡이 지름이
    # bar_h 의 정수배(≈2.0)가 되는지 확인.
    W, H = 1920, 1080
    margin_x, bar_w, bar_h, pb_y = mv.progress_bar_geometry(W, H, 1.0, "bottom")
    handle_d = max(bar_h + 2, int(round(bar_h * 2.0)))
    assert handle_d == round(bar_h * 2.0)
    assert handle_d > bar_h  # 트랙보다 뚜렷하게 커야 손잡이로 보인다


# ---------- 제목/아티스트 캡션 글자 크기 (title_caption_geometry) ----------

def test_title_caption_geometry_font_sizes_match_reference_ratios():
    # 레퍼런스(sample/playlist_sample1.png) 실측: 제목/아티스트 바운딩박스
    # 높이 비율 ≈48:27(≈1.78), 제목-상단→아티스트-상단 간격/제목폰트 ≈1.3배.
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        True, D=400, cy=324, H=1080, scale=1.0)
    assert ttl_fs == 62
    assert art_fs == 35
    assert art_gap == int(round(ttl_fs * 1.3))
    # 기존(52/30) 대비 눈에 띄게 커져 레퍼런스처럼 굵고 큰 타이틀이 되어야 한다
    assert ttl_fs > 52 and art_fs > 30
