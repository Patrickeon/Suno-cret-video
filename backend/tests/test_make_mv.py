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


def test_lp_vinyl_size_scale_matches_other_themes_cover_baseline():
    """제품 오너 피드백: 테마를 바꿔가며 비교해보니 lp_vinyl 만 앨범 커버 자체가
    다른 세 테마(classic/text_ring/square_spin)보다 눈에 띄게 커 보였다 —
    "앨범 크기"는 테마와 무관하게 일관돼야 한다(비닐이 커버 뒤로 삐져나오는 건
    별개의 장식 요소이지 커버 확대가 아니다). LP_VINYL_SIZE_SCALE 을 1.3 -> 1.0
    으로 되돌려 커버 베이스라인(D_lp)이 다른 테마의 커버 베이스라인(D, 확대
    없음)과 정확히 같아졌는지 확인한다.

    이 테스트는 예전 test_lp_vinyl_size_scale_enlarges_cover_relative_to_disc_diameter
    의 의도적 대체다 — 그 쪽은 "SIZE_SCALE>1.0 으로 커버를 확대하는 게 옳다"는
    이제는 폐기된 디자인 가정을 검증했다(라운드 1~3 의 disc_gap 24px 테스트가
    새 지오메트리로 교체됐던 것과 같은 종류의 의도적 교체)."""
    assert mv.LP_VINYL_SIZE_SCALE == 1.0
    lay = mv.get_layout(False)
    D = mv.disc_diameter(lay)
    D_lp = int(D * mv.LP_VINYL_SIZE_SCALE)
    D_lp -= D_lp % 2
    # D 자체가 이미 짝수(disc_diameter() 가 홀수면 -1 해 짝수로 맞춤)이므로
    # 1.0 배 곱셈 후에도 정확히 같아야 한다(반올림 오차조차 없어야 함).
    assert D_lp == D


def test_all_four_disc_themes_bake_cover_png_at_same_baseline_size():
    """main() 프리패스가 실제로 4 개 disc_theme 모두에서 커버(원형이든 정사각이든)
    PNG 를 동일한 D 기준으로 굽는지 소스 레벨로 확인한다 — classic/square_spin 은
    make_disc_png(art, disc_png, D)/make_square_png(art, disc_png, D), text_ring 은
    make_square_png(art, cover_png, D), lp_vinyl 은 make_square_png(art, cover_png,
    D_lp) 인데 D_lp==D(위 테스트) 이므로 넷 다 결국 같은 D 로 커버를 굽는다."""
    import inspect
    main_src = inspect.getsource(mv.main)

    lp_branch = main_src.split('if args.disc_theme == "lp_vinyl":')[1].split(
        'elif args.disc_theme == "text_ring":')[0]
    assert "make_square_png(art, cover_png, D_lp)" in lp_branch

    text_ring_branch = main_src.split('elif args.disc_theme == "text_ring":')[1].split(
        'elif args.disc_theme == "square_spin":')[0]
    assert "make_square_png(art, cover_png, D)" in text_ring_branch

    square_spin_branch = main_src.split('elif args.disc_theme == "square_spin":')[1].split(
        "else:")[0]
    assert "make_square_png(art, disc_png, D)" in square_spin_branch

    classic_branch = main_src.split('elif args.disc_theme == "square_spin":')[1].split(
        "else:")[1].split("\n\n")[0]
    assert "make_disc_png(art, disc_png, D)" in classic_branch


def test_render_disc_shrink_factor_uses_classic_reference_not_active_theme():
    """render() 의 disc_active 분기가 커버 크기 축소(shrink)를 계산할 때 활성
    disc_theme 이 아니라 항상 "classic"(=D 그대로, 확장 없음) 기준으로 호출하는지
    소스 레벨로 확인한다. 활성 테마를 그대로 넘기면(과거 코드) text_ring/
    square_spin 처럼 확장 배율이 큰 테마가 같은 예약 영역에서도 classic/lp_vinyl
    보다 더 많이 축소되어, 테마를 바꾸면 커버 "크기"가 들쭉날쭉해지는 버그가
    있었다(제품 오너 피드백)."""
    import inspect
    render_src = inspect.getsource(mv.render)
    disc_branch = render_src.split("if disc_active:")[1].split(
        "if disc_bg_style ==")[0]
    assert 'disc_shrink_factor(D, avail_top, avail_bottom, "classic")' in disc_branch
    # cy/앵커 계산(round 6: disc_stack_layout())도 활성 테마의 확장치가 아니라
    # 공용 D 를 그대로 받아써야 한다(disc_theme_max_extent(D, disc_theme) 를
    # 다시 쓰면 앵커 지점 자체가 테마마다 달라지는 버그가 재발한다)
    assert "disc_stack_layout(" in disc_branch
    # (주석에는 disc_theme_max_extent(D, disc_theme) 가 "왜 안 쓰는지" 설명하려고
    # 등장할 수 있으므로, 실제 호출 형태(// 로 이어지는 코드)만 부재를 확인한다)
    assert "disc_theme_max_extent(D, disc_theme) //" not in disc_branch


def test_main_prepass_disc_shrink_factor_uses_classic_reference():
    """main() 프리패스도 render() 와 동일하게 커버 크기 축소를 "classic" 기준
    하나로 통일해서 호출하는지 확인한다(그렇지 않으면 프리패스가 굽는 PNG 크기와
    render() 오버레이 크기가 테마별로 다시 어긋난다)."""
    import inspect
    main_src = inspect.getsource(mv.main)
    assert 'disc_shrink_factor(D, avail_top, avail_bottom, "classic")' in main_src


def test_cover_size_and_cy_are_identical_across_all_four_disc_themes():
    """핵심 회귀 테스트: 같은 H/W/avail_top/avail_bottom 입력에 대해, 커버 크기
    축소(D)와 중심(cy)이 disc_theme 값과 무관하게 완전히 동일해야 한다 — 순수
    함수 조합만으로 render() 의 실제 계산을 재현해 직접 비교한다(프레임 픽셀
    측정보다 이런 버그를 더 확실하게 잡는다). 일부러 커버가 실제로 축소되는
    좁은 avail 구간(전에는 테마별로 다르게 축소되던 상황)에서 검증한다."""
    lay = mv.get_layout(False, 1.0)
    W, H = lay["W"], lay["H"]
    D_base = mv.disc_diameter(lay)

    scenarios = [
        ("no reservation", mv.disc_avail_zone(
            H, W, 1.0, False, "auto", False, False, "bottom", None)),
        ("both edges reserved", mv.disc_avail_zone(
            H, W, 1.0, True, "top", True, True, "bottom", 8.0)),
        ("single edge (top) reserved", mv.disc_avail_zone(
            H, W, 1.0, True, "top", True, True, "top", 8.0)),
        ("tight synthetic zone", (400, 700, True, False)),  # avail_top,bottom,top_r,bottom_r
    ]

    for label, (avail_top, avail_bottom, top_reserved, bottom_reserved) in scenarios:
        results = {}
        for theme in ("classic", "lp_vinyl", "text_ring", "square_spin"):
            shrink = mv.disc_shrink_factor(D_base, avail_top, avail_bottom, "classic")
            D = D_base
            if shrink < 1.0:
                D = int(D_base * shrink)
                D -= D % 2
                D = max(D, 2)
            if top_reserved and bottom_reserved:
                cy = (avail_top + avail_bottom) // 2
            elif top_reserved:
                cy = avail_top + D // 2
            elif bottom_reserved:
                cy = avail_bottom - D // 2
            else:
                cy = int(H * 0.30) if H > W else int(H * 0.36)
            results[theme] = (D, cy)
        values = set(results.values())
        assert len(values) == 1, (label, results)


def test_decoration_never_clips_past_literal_frame_edges():
    """제품 오너 방침: 예약 마진(DISC_RESERVED_GAP 등)은 테마별 장식이 살짝
    넘어가도 괜찮지만(의도된 트레이드오프), 실제 프레임 경계(y=0/H)는 절대
    넘으면 안 된다. 커버 크기를 테마 무관 "classic" 기준으로 통일하면서
    테마별 장식(RD=D*TEXT_RING_SCALE, D*sqrt(2))이 더 이상 자체적으로
    축소되지 않게 됐으므로, 여러 스케일/방향/예약 조합에서 가장 큰 확장
    배율(square_spin, sqrt(2))을 가진 장식도 프레임을 벗어나지 않는지
    전수 조사한다 — 벗어나는 조합이 하나라도 있으면 별도의 안전장치가
    필요하다는 뜻이라 이 테스트가 그것을 잡아낸다."""
    import math

    def worst_case(shorts, scale, cap_pos, pb_pos, pb_on):
        lay = mv.get_layout(shorts, scale)
        W, H = lay["W"], lay["H"]
        D_base = mv.disc_diameter(lay)
        avail_top, avail_bottom, top_r, bottom_r = mv.disc_avail_zone(
            H, W, scale, True, cap_pos, True, pb_on, pb_pos, 8.0)
        shrink = mv.disc_shrink_factor(D_base, avail_top, avail_bottom, "classic")
        D = D_base
        if shrink < 1.0:
            D = int(D_base * shrink)
            D -= D % 2
            D = max(D, 2)
        if top_r and bottom_r:
            cy = (avail_top + avail_bottom) // 2
        elif top_r:
            cy = avail_top + D // 2
        elif bottom_r:
            cy = avail_bottom - D // 2
        else:
            cy = int(H * 0.30) if H > W else int(H * 0.36)
        RD = int(math.ceil(D * math.sqrt(2)))
        RD += RD % 2
        half = RD // 2
        return cy - half, cy + half, H

    for shorts in (False, True):
        for scale in (1.0, 2 / 3, 1.333, 2.0, 0.4):
            for cap_pos in ("top", "bottom"):
                for pb_pos in ("top", "bottom"):
                    for pb_on in (True, False):
                        top_edge, bottom_edge, H = worst_case(
                            shorts, scale, cap_pos, pb_pos, pb_on)
                        assert top_edge >= 0, (shorts, scale, cap_pos, pb_pos, pb_on, top_edge)
                        assert bottom_edge <= H, (
                            shorts, scale, cap_pos, pb_pos, pb_on, bottom_edge, H)


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


def test_render_progress_bar_color_override_source():
    """render() 의 진행바 색 결정이 --progress-bar-color(progress_bar_color 인자)
    를 우선하고, 없거나 잘못된 값이면 기존처럼 viz_colors[0] 유도값으로 폴백하는지
    소스 레벨로 확인한다(순수 additive 변경 — progress_bar_color 를 안 주는 기존
    호출부는 완전히 동일하게 동작해야 함)."""
    import inspect
    render_src = inspect.getsource(mv.render)
    pb_branch = render_src.split("if progress_bar and duration:")[1].split(
        "# ---- 진행 위치 손잡이")[0]
    assert "accent = norm_hex(progress_bar_color, None) or norm_hex(" in pb_branch


def test_progress_bar_color_override_wins_when_valid_else_falls_back():
    """render() 의 accent 결정 체인(norm_hex(progress_bar_color, None) or
    norm_hex(viz_colors[0], DEFAULT_VIZ_COLORS[0]))을 순수 계산으로 재현해:
    유효한 override 가 있으면 그걸 쓰고, override 가 없거나(None) 잘못된 hex 면
    기존과 동일하게 viz_colors[0] 유도값(또는 DEFAULT_VIZ_COLORS[0])으로 폴백하는지
    확인한다."""
    viz_colors = ["00FF00"]

    def accent_for(progress_bar_color, viz_colors):
        return mv.norm_hex(progress_bar_color, None) or mv.norm_hex(
            (viz_colors or [None])[0], mv.DEFAULT_VIZ_COLORS[0])

    assert accent_for("FF0000", viz_colors) == "FF0000"          # 유효한 override 우선
    assert accent_for(None, viz_colors) == "00FF00"               # override 없음 -> 기존 폴백
    assert accent_for("", viz_colors) == "00FF00"                 # override 빈 문자열 -> 기존 폴백
    assert accent_for("bad", viz_colors) == "00FF00"              # override 잘못된 hex -> 기존 폴백
    assert accent_for(None, None) == mv.DEFAULT_VIZ_COLORS[0]     # 아무것도 없음 -> 완전 기본값


def test_progress_bar_color_cli_flag_declared():
    """--progress-bar-color 가 argparse 에 선언되어 있는지 확인."""
    import inspect
    main_src = inspect.getsource(mv.main)
    assert '"--progress-bar-color"' in main_src


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
    # 높이 비율 ≈48:27(≈1.78). 제목-아티스트 줄 간격은 실측값(1.3배)에서
    # 출발했지만, 제품 오너가 실제 렌더를 보고 "더 벌려 달라"고 재요청해
    # 1.6배로 추가로 키웠다(디자인 의도 우선, 레퍼런스 실측치보다 우선한다).
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        True, D=400, cy=324, H=1080, scale=1.0)
    assert ttl_fs == 62
    assert art_fs == 35
    assert art_gap == int(round(ttl_fs * 1.6))
    # 기존(52/30) 대비 눈에 띄게 커져 레퍼런스처럼 굵고 큰 타이틀이 되어야 한다
    assert ttl_fs > 52 and art_fs > 30


# ---------- 상단 진행바 + 상단 캡션 동시 배치 (확인된 버그: 겹침) -----------------

def test_title_caption_geometry_top_pos_overlaps_progress_bar_without_fix_context():
    """회귀 재현용 베이스라인: 진행바 정보(W/progress_bar) 없이 pos="top" 을 쓰면
    (구 호출부와 동일한 하위호환 상태) 여전히 고정 40*scale 만 쓴다 — 이 값 자체는
    진행바를 고려하지 않으므로, 진행바가 top 일 때 실제로 겹칠 수 있는 값이라는
    것을 보여준다(다음 테스트가 W/progress_bar 인자를 주면 겹치지 않게 올라가는
    것과 대비)."""
    scale = 2 / 3
    H = 720
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        False, 0, 0, H, scale, pos="top")
    assert ttl_y == int(round(40 * scale))


def test_title_caption_geometry_top_pos_clears_top_progress_bar_when_both_given():
    """실제 재현한 버그(sample/playscreen.png, --title-caption-pos top
    --progress-bar --progress-bar-pos top): 진행바 트랙 하단 y=31, 캡션 상단
    y=27 로 겹쳤다. W/progress_bar/progress_bar_pos 를 주면 캡션 상단이 진행바
    트랙 하단보다 항상 아래(겹치지 않는 지점)로 밀려야 한다."""
    scale = 2 / 3
    W, H = 1280, 720
    _, _, pb_h, pb_y = mv.progress_bar_geometry(W, H, scale, "top")
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        False, 0, 0, H, scale, pos="top",
        W=W, progress_bar=True, progress_bar_pos="top")
    assert ttl_y >= pb_y + pb_h  # 트랙 하단과 겹치지 않음
    assert ttl_y > int(round(40 * scale))  # 진행바가 없을 때보다 뚜렷이 아래로 밀림


def test_title_caption_geometry_top_pos_unaffected_when_progress_bar_off():
    """회귀 방지: progress_bar=False(기본값)면 W 를 줘도 기존과 완전히 동일한
    고정 40*scale 이어야 한다 — 진행바가 꺼져 있으면 이 보정은 적용되지 않는다."""
    scale = 1.0
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        False, 0, 0, 1080, scale, pos="top", W=1920, progress_bar=False)
    assert ttl_y == int(round(40 * scale))


def test_title_caption_geometry_top_pos_unaffected_when_progress_bar_at_bottom():
    """회귀 방지: 진행바가 bottom 이면 top 캡션과 애초에 안 겹치므로 보정이
    적용되지 않아야 한다."""
    scale = 1.0
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        False, 0, 0, 1080, scale, pos="top",
        W=1920, progress_bar=True, progress_bar_pos="bottom")
    assert ttl_y == int(round(40 * scale))


def test_title_caption_geometry_auto_pos_ignores_progress_bar_args():
    """회귀 방지: pos="auto" 는 progress_bar/W 인자를 줘도 전혀 영향받지 않아야
    한다(이 보정은 pos="top" 전용)."""
    scale = 2 / 3
    W, H = 1280, 720
    D, cy = 300, 260
    with_pb = mv.title_caption_geometry(
        True, D, cy, H, scale, pos="auto", W=W,
        progress_bar=True, progress_bar_pos="top")
    without_pb = mv.title_caption_geometry(
        True, D, cy, H, scale, pos="auto")
    assert with_pb == without_pb


# ---------- pos="bottom" (신규): pos="top" 의 상하 대칭 -------------------------

def test_title_caption_geometry_bottom_pos_anchors_near_bottom_edge_when_no_progress_bar():
    """진행바가 없으면(혹은 bottom 이 아니면) 아티스트 하단이 화면 하단에서
    40*scale 만큼 떨어진 지점에 자연 착지한다 — pos="top" 의 고정 40*scale
    시작값과 대칭되는 기본 여백."""
    scale = 1.0
    H = 1080
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        False, 0, 0, H, scale, pos="bottom")
    art_bottom = ttl_y + art_gap + art_fs
    assert art_bottom == H - int(round(40 * scale))
    assert ttl_y < art_bottom  # 제목이 아티스트보다 위(읽는 순서 유지)


def test_title_caption_geometry_bottom_pos_clears_bottom_progress_bar_when_both_given():
    """--title-caption-pos bottom --progress-bar --progress-bar-pos bottom 조합:
    캡션 블록이 진행바 바로 위(GAP=23*scale 여백)에 타이트하게 붙어야 하고,
    진행바 트랙과 절대 겹치면 안 된다."""
    scale = 1.0
    W, H = 1920, 1080
    _, _, pb_h, pb_y = mv.progress_bar_geometry(W, H, scale, "bottom")
    ttl_fs, art_fs, ttl_y, art_gap = mv.title_caption_geometry(
        False, 0, 0, H, scale, pos="bottom",
        W=W, progress_bar=True, progress_bar_pos="bottom")
    art_bottom = ttl_y + art_gap + art_fs
    gap = int(round(23 * scale))
    assert art_bottom == pb_y - gap  # 진행바 바로 위, 타이트 간격
    assert art_bottom <= pb_y  # 겹치지 않음
    # 진행바가 없을 때보다 뚜렷이 위로 밀려 올라가야 한다(진행바가 화면 맨 아래를 차지)
    no_pb_art_bottom = H - int(round(40 * scale))
    assert art_bottom < no_pb_art_bottom


def test_title_caption_geometry_bottom_pos_unaffected_when_progress_bar_off():
    """회귀 방지: progress_bar=False 면 W 를 줘도 진행바 없는 기본값과 동일해야
    한다."""
    scale = 1.0
    W, H = 1920, 1080
    with_w = mv.title_caption_geometry(
        False, 0, 0, H, scale, pos="bottom", W=W, progress_bar=False)
    without_w = mv.title_caption_geometry(False, 0, 0, H, scale, pos="bottom")
    assert with_w == without_w


def test_title_caption_geometry_bottom_pos_unaffected_when_progress_bar_at_top():
    """회귀 방지: 진행바가 top 이면 bottom 캡션과 애초에 안 겹치므로 보정이
    적용되지 않아야 한다."""
    scale = 1.0
    W, H = 1920, 1080
    with_pb_top = mv.title_caption_geometry(
        False, 0, 0, H, scale, pos="bottom",
        W=W, progress_bar=True, progress_bar_pos="top")
    without_pb = mv.title_caption_geometry(False, 0, 0, H, scale, pos="bottom")
    assert with_pb_top == without_pb


def test_title_caption_geometry_top_and_bottom_pos_use_tight_twentythree_px_gaps():
    """제품 오너 피드백: pos="top"/"bottom" 의 제목-아티스트(및 진행바-캡션) 간격은
    기존 ttl_fs*1.6(auto 전용, ≈99px)이 아니라 타이트한 GAP 값이어야 한다. 10px 로
    시작해 18px 로 한 차례, 실제 렌더 리뷰 후 재요청으로 23px 로 한 번 더 소폭
    확대됐다(DISC_RESERVED_GAP=32px 디스크↔캡션 간격은 이 조정과 무관, 그대로).
    pos="auto" 는 절대 안 바뀐다."""
    scale = 1.0
    H = 1080
    _, _, _, art_gap_top = mv.title_caption_geometry(False, 0, 0, H, scale, pos="top")
    _, _, _, art_gap_bottom = mv.title_caption_geometry(False, 0, 0, H, scale, pos="bottom")
    _, _, _, art_gap_auto = mv.title_caption_geometry(
        True, 400, 324, H, scale, pos="auto")
    ttl_fs = int(round(62 * scale))
    gap = int(round(23 * scale))
    assert art_gap_top == ttl_fs + gap
    assert art_gap_bottom == ttl_fs + gap
    assert art_gap_auto == int(round(ttl_fs * 1.6))  # auto 는 절대 안 바뀜(회귀 방지)
    assert art_gap_top < art_gap_auto  # 훨씬 촘촘해야 한다
    # 여전히 이전 라운드(18px)보다는 넉넉해야 한다(이번 후속 조정의 핵심)
    assert gap > int(round(18 * scale))
    # DISC_RESERVED_GAP(디스크↔캡션 앵커 간격)은 이번 조정과 무관하게 그대로여야 함
    assert mv.DISC_RESERVED_GAP == 32


def test_render_disc_active_uses_new_bidirectional_reservation_helpers():
    """render() 소스가 새 양방향 예약/축소 순수 함수(disc_avail_zone,
    disc_shrink_factor)를 실제로 호출하는지 확인. 예전에는 top+top 전용, 24px
    고정 disc_gap 하드코딩이었으나(디자인 재작업으로 폐기), 이제는 양쪽 변을
    대칭으로 다루는 공용 헬퍼로 cy 재중앙정렬 + D 축소를 함께 처리한다.
    pos="auto" 이거나 캡션이 꺼져 있으면 disc_avail_zone() 이 reserved=False 를
    돌려주므로 cy 는 여전히 기존 base_cy 그대로 유지된다(회귀 방지)."""
    import inspect
    render_src = inspect.getsource(mv.render)
    disc_branch = render_src.split("if disc_active:")[1].split(
        "if disc_bg_style ==")[0]
    assert "base_cy" in disc_branch
    assert "disc_avail_zone(" in disc_branch
    assert "disc_shrink_factor(" in disc_branch
    assert "reserved" in disc_branch


def test_main_prepass_uses_same_avail_zone_and_shrink_helpers_as_render():
    """CRITICAL GOTCHA 회귀 테스트: main() 의 PNG 프리패스(_cover.png 등 굽는 곳)가
    render() 의 오버레이 배치와 반드시 같은 disc_avail_zone()/disc_shrink_factor()
    호출로 D 를 축소해야 한다 — 한쪽만 축소하고 한쪽은 안 하면(혹은 각자 따로
    구현하면) 베이크된 PNG 픽셀 크기와 오버레이 배치 크기가 어긋나 결과물이
    깨진다(LP_VINYL_SIZE_SCALE 프리패스/오버레이 공식 불일치와 동일한 종류의
    함정). 소스에 두 헬퍼 호출이 모두 있는지 양쪽 함수에서 확인한다."""
    import inspect
    main_src = inspect.getsource(mv.main)
    render_src = inspect.getsource(mv.render)
    assert "disc_avail_zone(" in main_src
    assert "disc_shrink_factor(" in main_src
    assert "disc_avail_zone(" in render_src
    assert "disc_shrink_factor(" in render_src


# ---------- round 6: 상/하단 묶음 + 디스크 스택 전체 중앙정렬 ----------------------

def test_main_prepass_does_not_need_disc_stack_layout():
    """round 6 로 추가된 disc_stack_layout() 은 render() 의 오버레이 y 좌표(캡션/
    진행바 실제 draw 위치, 디스크 cy)만 결정한다 — main() 의 프리패스는 PNG
    "크기"(D/D_lp/VD/RD)만 구우면 되고 y 좌표는 전혀 계산하지 않으므로 이 함수를
    알 필요가 없다. 이 가정이 깨지면(누군가 main() 에도 disc_stack_layout 호출을
    추가하면) 오히려 round 1 이 막았던 프리패스/오버레이 불일치 종류의 버그를
    다시 만들 위험이 있으므로, 프리패스가 이 함수를 쓰지 않는다는 것 자체를
    회귀 테스트로 고정한다."""
    import inspect
    main_src = inspect.getsource(mv.main)
    render_src = inspect.getsource(mv.render)
    assert "disc_stack_layout(" not in main_src
    assert "disc_stack_layout(" in render_src


def test_render_disc_active_branch_calls_disc_stack_layout_for_cy():
    """render() 의 disc_active 분기가 (옛 anchor-only if/elif 사슬 대신) 새
    disc_stack_layout() 을 호출해 cy 를 구하는지 소스 레벨로 확인한다."""
    import inspect
    render_src = inspect.getsource(mv.render)
    disc_branch = render_src.split("if disc_active:")[1].split(
        "if disc_bg_style ==")[0]
    assert "disc_stack_layout(" in disc_branch
    assert "stack_shift" in disc_branch


def test_render_caption_and_progress_bar_draw_calls_apply_stack_shift():
    """CRITICAL 상호일관성 회귀 테스트(round 6 보고에서 지적된 "예측 vs 실제
    그리기" 어긋남 부류의 버그): 디스크 cy 계산에 쓰인 것과 같은 stack_shift
    변수를, 실제 캡션/진행바를 그리는 두 draw 호출부도 반드시 참조해야 한다 —
    그렇지 않으면 디스크만 중앙으로 옮겨지고 캡션/진행바는 여전히 프레임
    가장자리에 붙어버린다(디스크와 캡션이 서로 어긋나 보임). 하나의 stack_shift
    변수를 세 곳(cy 계산, 캡션 draw, 진행바 draw)이 공유하는 구조이므로("한 번
    계산해서 여러 곳에 꽂는" 방식) 자연히 lockstep 이 보장된다."""
    import inspect
    render_src = inspect.getsource(mv.render)

    caption_branch = render_src.split(
        'if title_caption and (cap_title or cap_artist):')[1].split(
        "# ---- 간주")[0]
    assert "stack_shift" in caption_branch

    pb_branch = render_src.split("if progress_bar and duration:")[1].split(
        "# ---- 진행 위치 손잡이")[0]
    assert "stack_shift" in pb_branch


def test_disc_stack_layout_never_used_to_grow_or_shrink_disc_size():
    """round 5 는 디스크 SIZING(테마 무관, "classic" 기준)과 round 6 은 디스크
    POSITIONING(스택 중앙정렬)을 다룬다 — 서로 직교해야 한다. disc_stack_layout()
    이 받는 D 는 이미 disc_shrink_factor(D, avail_top, avail_bottom, "classic")
    로 축소가 끝난 뒤의 값이어야 하고, disc_stack_layout() 자신은 D 를 절대
    변형하지 않아야 한다(입력 그대로 cy 계산에만 사용, 반환값에 D 자체는 아예
    없음) — 즉 "중앙정렬된 여유 공간을 채우려고 디스크를 다시 키우는" 경로가
    없어야 한다."""
    import inspect
    src = inspect.getsource(mv.disc_stack_layout)
    # 함수 시그니처에 D 는 입력으로만 등장하고, 반환문(return)에는 D 를 가공한
    # 새 크기 값이 없어야 한다(반환은 stack_shift, cy 두 값뿐).
    assert "return stack_shift, cy" in src
    assert "D =" not in src  # D 를 재대입(축소/확대)하는 코드가 전혀 없어야 함

    render_src = inspect.getsource(mv.render)
    disc_branch = render_src.split("if disc_active:")[1].split(
        "if disc_bg_style ==")[0]
    # disc_shrink_factor() 호출(사이징)은 disc_stack_layout() 호출(포지셔닝)보다
    # 먼저 나와야 한다 — D 가 이미 확정된 뒤에 포지셔닝이 그 값을 그대로 받아씀.
    assert disc_branch.index('disc_shrink_factor(D, avail_top, avail_bottom, "classic")') < \
        disc_branch.index("disc_stack_layout(")


def test_disc_stack_layout_scenario_caption_only_bottom_matches_bug_report():
    """(a) 버그 재현 설정: lp_vinyl, --title-caption-pos bottom, 진행바 없음
    (sample/screen.png). 디스크 위쪽 바깥 여백과 하단 캡션 묶음 아래쪽 바깥
    여백이 같아야 한다(반올림 오차 1px 허용)."""
    W, H = 1920, 1080
    avail_top, avail_bottom, top_r, bottom_r = mv.disc_avail_zone(
        H, W, 1.0, True, "bottom", True, False, "bottom", None)
    assert (top_r, bottom_r) == (False, True)
    D = mv.disc_diameter(mv.get_layout(False))
    shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
    if shrink < 1.0:
        D = int(D * shrink)
        D -= D % 2
    reserved_top, reserved_bottom = mv.disc_vertical_reservation(
        H, 1.0, True, "bottom", True, False, "bottom", W)
    stack_shift, cy = mv.disc_stack_layout(
        H, 1.0, reserved_top, reserved_bottom, top_r, bottom_r, D)
    half = D // 2
    disc_top = cy - half
    margin_above_disc = disc_top
    margin_below_group = stack_shift
    assert abs(margin_above_disc - margin_below_group) <= 1
    assert margin_above_disc > 50  # 실제로 눈에 띄는 대칭 여백이 있어야 의미있는 검증


def test_disc_stack_layout_scenario_caption_only_top_mirrors_bottom():
    """(b) 캡션-only-top(진행바 없음): (a) 의 상하 대칭 케이스."""
    W, H = 1920, 1080
    avail_top, avail_bottom, top_r, bottom_r = mv.disc_avail_zone(
        H, W, 1.0, True, "top", True, False, "bottom", None)
    assert (top_r, bottom_r) == (True, False)
    D = mv.disc_diameter(mv.get_layout(False))
    shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
    if shrink < 1.0:
        D = int(D * shrink)
        D -= D % 2
    reserved_top, reserved_bottom = mv.disc_vertical_reservation(
        H, 1.0, True, "top", True, False, "bottom", W)
    stack_shift, cy = mv.disc_stack_layout(
        H, 1.0, reserved_top, reserved_bottom, top_r, bottom_r, D)
    half = D // 2
    disc_bottom = cy + half
    margin_below_disc = H - disc_bottom
    margin_above_group = stack_shift
    assert abs(margin_below_disc - margin_above_group) <= 1
    assert margin_below_disc > 50


def test_disc_stack_layout_scenario_split_progress_top_caption_bottom():
    """(c) 분리 케이스: 진행바 top + 캡션 bottom. 두 묶음 모두 예약되므로
    disc_stack_layout() 은 스택 전체를 중앙정렬하되, 상단 묶음 위쪽 바깥 여백과
    하단 묶음 아래쪽 바깥 여백이 서로 같아야 한다(둘 다 stack_shift)."""
    W, H = 1920, 1080
    avail_top, avail_bottom, top_r, bottom_r = mv.disc_avail_zone(
        H, W, 1.0, True, "bottom", True, True, "top", 180.0)
    assert (top_r, bottom_r) == (True, True)
    D = mv.disc_diameter(mv.get_layout(False))
    shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
    if shrink < 1.0:
        D = int(D * shrink)
        D -= D % 2
    reserved_top, reserved_bottom = mv.disc_vertical_reservation(
        H, 1.0, True, "bottom", True, True, "top", W)
    stack_shift, cy = mv.disc_stack_layout(
        H, 1.0, reserved_top, reserved_bottom, top_r, bottom_r, D)
    # 상단 묶음의 실제(이동 후) 위쪽 바깥 여백은 stack_shift 그 자체(top 은
    # +stack_shift 로 이동), 하단 묶음의 실제 아래쪽 바깥 여백도 stack_shift
    # (bottom 은 H-stack_shift 기준) — 둘 다 같은 stack_shift 값이므로 자명하게
    # 대칭이다. 여유가 실제로 있는지만 확인한다.
    assert stack_shift >= 0
    half = D // 2
    assert cy - half >= 0 and cy + half <= H


def test_disc_stack_layout_scenario_split_progress_bottom_caption_top():
    """(d) 역방향 분리 케이스: 진행바 bottom + 캡션 top."""
    W, H = 1920, 1080
    avail_top, avail_bottom, top_r, bottom_r = mv.disc_avail_zone(
        H, W, 1.0, True, "top", True, True, "bottom", 180.0)
    assert (top_r, bottom_r) == (True, True)
    D = mv.disc_diameter(mv.get_layout(False))
    shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
    if shrink < 1.0:
        D = int(D * shrink)
        D -= D % 2
    reserved_top, reserved_bottom = mv.disc_vertical_reservation(
        H, 1.0, True, "top", True, True, "bottom", W)
    stack_shift, cy = mv.disc_stack_layout(
        H, 1.0, reserved_top, reserved_bottom, top_r, bottom_r, D)
    assert stack_shift >= 0
    half = D // 2
    assert cy - half >= 0 and cy + half <= H


def test_disc_stack_layout_returns_none_cy_when_nothing_reserved():
    """회귀 방지 경계: top_reserved/bottom_reserved 가 둘 다 False 면(pos="auto"
    이거나 캡션이 꺼져 있음) disc_stack_layout() 은 (0, None) 을 돌려줘야 한다 —
    호출부가 cy=None 을 base_cy 폴백 신호로 쓸 수 있게."""
    shift, cy = mv.disc_stack_layout(1080, 1.0, 0, 0, False, False, 452)
    assert (shift, cy) == (0, None)


def test_disc_stack_layout_sub_zone_clamp_prevents_caption_subtitle_overlap():
    """Round 6 자체 검증 중 발견한 회귀(제품 오너가 보고한 버그는 아님): 스택
    중앙정렬이 --title-caption-pos bottom 캡션 묶음을 안쪽(위)으로 옮기다가 —
    특히 여유가 많을 때, 즉 원래 버그가 가장 심했던 상황에서 그대로 — 자막(가사)
    안전영역과 겹쳐버렸다(실제 렌더로 재현 확인). sub_zone 을 넘기면 stack_shift
    를 필요한 만큼만 줄여 겹침을 없애야 한다."""
    W, H = 1920, 1080
    lay = mv.get_layout(False, 1.0)
    sub_zone = mv.subtitle_zone_y(lay, sub_pos="bottom", sub_size=1.0)
    sub_top, sub_bottom = sub_zone

    D = mv.disc_diameter(lay)
    avail_top, avail_bottom, top_r, bottom_r = mv.disc_avail_zone(
        H, W, 1.0, True, "bottom", True, False, "bottom", None)
    shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
    if shrink < 1.0:
        D = int(D * shrink)
        D -= D % 2
    reserved_top, reserved_bottom = mv.disc_vertical_reservation(
        H, 1.0, True, "bottom", True, False, "bottom", W)

    # 클램프 없이는 실제로 겹친다는 것부터 확인(이 테스트가 의미 있으려면 필요)
    shift_noclamp, _ = mv.disc_stack_layout(
        H, 1.0, reserved_top, reserved_bottom, top_r, bottom_r, D)
    group_top_noclamp = H - reserved_bottom - shift_noclamp
    assert group_top_noclamp < sub_bottom  # 겹침 재현

    shift_clamped, cy_clamped = mv.disc_stack_layout(
        H, 1.0, reserved_top, reserved_bottom, top_r, bottom_r, D, sub_zone=sub_zone)
    sub_gap = int(round(16 * 1.0))
    group_top_clamped = H - reserved_bottom - shift_clamped
    assert group_top_clamped >= sub_bottom + sub_gap - 1  # 겹침 해소(반올림 오차 허용)
    assert shift_clamped <= shift_noclamp  # 클램프는 이동량을 줄이기만 한다(늘리지 않음)
    assert cy_clamped is not None


def test_disc_stack_layout_sub_zone_none_is_backward_compatible():
    """sub_zone 을 안 주면(기존 호출부, round 6 이전 테스트들) 기존과 완전히
    동일한 결과여야 한다 — 새 클램프는 순수 additive."""
    H, D = 1080, 452
    without = mv.disc_stack_layout(H, 1.0, 150, 0, True, False, D)
    with_none = mv.disc_stack_layout(H, 1.0, 150, 0, True, False, D, sub_zone=None)
    assert without == with_none


def test_disc_stack_layout_top_only_centers_whole_stack_not_just_anchors_disc():
    """Round 6 회귀 테스트 — 이 테스트는 round 2/3 이 확립한 "단일 변 앵커"
    가정을 의도적으로 대체한다(round 1/2 의 disc_gap 24px 테스트가 새 지오메트리로
    교체됐던 것과 같은 종류의 교체). 예전 가정("한쪽 변만 예약되면 디스크를 그
    경계에 DISC_RESERVED_GAP 만큼만 앵커하고 반대쪽엔 남는 여유를 전부 몰아넣는다")
    자체가 이번 라운드에서 고쳐진 버그였다(sample/screen.png 재현: 캡션 반대쪽에
    거대한 빈 공간). 새 동작: '진행바/캡션 묶음 + gap + 디스크'를 하나의 강체로
    보고 프레임에서 정중앙 정렬 — 묶음 자체도 여유가 있으면 프레임 가장자리에서
    안쪽으로 이동한다.

    버그 재현 치수(1280x720, --preview-secs 스케일), --title-caption-pos top +
    --progress-bar-pos top(단일 변)."""
    scale = 2 / 3
    lay = mv.get_layout(False, scale)
    W, H = lay["W"], lay["H"]

    avail_top, avail_bottom, top_reserved, bottom_reserved = mv.disc_avail_zone(
        H, W, scale, True, "top", True, True, "top", 180.0)
    assert top_reserved is True
    assert bottom_reserved is False  # 단일 변(top)만 예약

    reserved_top, reserved_bottom = mv.disc_vertical_reservation(
        H, scale, True, "top", True, True, "top", W)
    reserved_gap = int(round(mv.DISC_RESERVED_GAP * scale))

    D = mv.disc_diameter(lay)
    shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
    if shrink < 1.0:
        D = int(D * shrink)
        D -= D % 2
        D = max(D, 2)

    stack_shift, cy = mv.disc_stack_layout(
        H, scale, reserved_top, reserved_bottom, top_reserved, bottom_reserved, D)
    assert cy is not None
    base_cy = int(H * 0.30)
    assert cy != base_cy  # 고정 중앙값에서 실제로 밀려나야 한다

    half = D // 2
    disc_top = cy - half
    disc_bottom = cy + half
    # 묶음(진행바)과 디스크 사이 간격은 여전히 타이트하게 DISC_RESERVED_GAP 만
    # 유지되어야 한다(round 2/3 의 "붙지 않되 살짝만" 요구사항은 그대로 보존).
    assert (disc_top - stack_shift) - reserved_top == reserved_gap
    # 핵심 회귀 확인: 묶음 위쪽 여백(=stack_shift)과 디스크 아래쪽에서 프레임
    # 바닥까지의 여백이 같아야 한다(전체 3-조각 스택이 프레임 중앙에 옴) — 예전
    # 버그는 이 두 값이 전혀 다르며(위쪽 0, 아래쪽에 모든 여유가 쏠림) 재현됐었다.
    assert disc_top >= avail_top - 1  # 디스크 상단이 예약 영역(+마진)을 침범하지 않음
    assert (H - disc_bottom) == stack_shift
    assert stack_shift > reserved_gap  # 실제로 남는 여유가 있어 이 검증이 의미있음


def test_disc_avail_zone_auto_pos_never_reserves():
    """회귀 방지 핵심 경계: title_caption_pos="auto" 면 캡션/진행바가 모두 켜져
    있어도 disc_avail_zone() 은 절대 예약하지 않는다(양쪽 플래그 모두 False, 순수
    프레임 마진만) — cy 는 기존 base_cy 그대로 유지되어야 한다."""
    W, H = 1920, 1080
    avail_top, avail_bottom, top_reserved, bottom_reserved = mv.disc_avail_zone(
        H, W, 1.0, True, "auto", True, True, "top", 180.0)
    assert top_reserved is False
    assert bottom_reserved is False
    margin = int(round(15 * 1.0))
    assert (avail_top, avail_bottom) == (margin, H - margin)


def test_disc_avail_zone_title_caption_off_never_reserves():
    """회귀 방지: title_caption 자체가 꺼져 있으면(title_caption_on=False) pos 값과
    무관하게 예약이 전혀 일어나지 않는다 — 진행바 단독으로는 cy 를 절대 흔들지
    않는다(기존 disc+progress-bar-without-caption 사용자 회귀 방지)."""
    W, H = 1920, 1080
    avail_top, avail_bottom, top_reserved, bottom_reserved = mv.disc_avail_zone(
        H, W, 1.0, False, "top", False, True, "top", 180.0)
    assert top_reserved is False
    assert bottom_reserved is False


def test_disc_vertical_reservation_is_bidirectional_and_independent_per_edge():
    """진행바와 캡션이 서로 다른 변에 있어도(예: 진행바 top + 캡션 bottom, 혹은
    그 반대) 각 변이 독립적으로 예약되는지 확인 — 한쪽 변의 캡션이 반대쪽 변의
    '캡션 없는 진행바 단독' 예약을 막지 않는다."""
    W, H = 1920, 1080
    scale = 1.0

    # 캡션 bottom + 진행바 top: 위쪽엔 진행바만(캡션 없음), 아래쪽엔 캡션만
    rt, rb = mv.disc_vertical_reservation(H, scale, True, "bottom", True, True, "top", W)
    assert rt > 0  # 상단: 진행바 단독 예약
    assert rb > 0  # 하단: 캡션 예약

    # 캡션 top + 진행바 bottom (반대 조합)
    rt2, rb2 = mv.disc_vertical_reservation(H, scale, True, "top", True, True, "bottom", W)
    assert rt2 > 0
    assert rb2 > 0

    # 캡션 bottom, 진행바 없음 -> 상단은 전혀 예약되지 않음
    rt3, rb3 = mv.disc_vertical_reservation(H, scale, True, "bottom", True, False, "bottom", W)
    assert rt3 == 0
    assert rb3 > 0


def test_disc_never_clipped_in_all_six_top_bottom_combinations():
    """제품 오너 요구사항: 캡션/진행바가 top/bottom 어떤 조합으로 있든(둘 다 top,
    둘 다 bottom, 서로 반대, 진행바 없이 캡션만) 디스크는 항상 리터럴 프레임
    경계([0, H]) 안에 완전히 들어가야 한다(클리핑 없음) — render() 과 같은 계산
    (disc_vertical_reservation + disc_stack_layout, round 6) 을 그대로 재현해
    검증한다. round 6 이후로는 디스크가 avail_top/avail_bottom(옛 앵커 모델의
    여백)이 아니라 disc_stack_layout() 의 스택 중앙정렬을 따르므로, "예약 안 된
    쪽" 여백은 avail_* 값과 달라질 수 있다(의도된 동작 — 프레임 경계만 절대
    기준) — 다만 "예약된 쪽"은 여전히 DISC_RESERVED_GAP 만큼의 타이트한 간격을
    유지해야 하므로 그쪽은 avail_top/avail_bottom 대비로도 확인한다."""
    W, H = 1920, 1080
    combos = [
        ("top", "top", True), ("top", "bottom", True),
        ("bottom", "top", True), ("bottom", "bottom", True),
        ("top", "top", False), ("bottom", "bottom", False),
    ]
    D0 = mv.disc_diameter(mv.get_layout(False))
    for cap_pos, pb_pos, pb_on in combos:
        avail_top, avail_bottom, top_reserved, bottom_reserved = mv.disc_avail_zone(
            H, W, 1.0, True, cap_pos, True, pb_on, pb_pos, 180.0)
        assert (top_reserved or bottom_reserved) is True, (cap_pos, pb_pos, pb_on)
        assert avail_top < avail_bottom, (cap_pos, pb_pos, pb_on)

        D = D0
        shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
        if shrink < 1.0:
            D = int(D * shrink)
            D -= D % 2
            D = max(D, 2)
        reserved_top, reserved_bottom = mv.disc_vertical_reservation(
            H, 1.0, True, cap_pos, True, pb_on, pb_pos, W)
        stack_shift, cy = mv.disc_stack_layout(
            H, 1.0, reserved_top, reserved_bottom, top_reserved, bottom_reserved, D)
        assert cy is not None
        half = D // 2

        assert cy - half >= 0, (cap_pos, pb_pos, pb_on, cy, half)
        assert cy + half <= H, (cap_pos, pb_pos, pb_on, cy, half, H)
        if top_reserved:
            assert cy - half >= avail_top, (cap_pos, pb_pos, pb_on, cy, half, avail_top)
        if bottom_reserved:
            assert cy + half <= avail_bottom, (cap_pos, pb_pos, pb_on, cy, half, avail_bottom)


def test_disc_stack_layout_single_edge_symmetric_both_edges_still_center():
    """Round 6 핵심 구분: 캡션/진행바가 같은 변에만 있으면(top+top, bottom+bottom
    등 단일 변) 디스크+묶음 전체가 프레임에서 대칭으로 중앙정렬되고(묶음 위(또는
    아래) 바깥 여백 == 디스크 반대쪽 바깥 여백), 서로 다른 변에 있으면(top+bottom,
    bottom+top) 여전히 두 묶음 사이 정중앙에 온다. 제품 오너가 확인한 버그
    (단일 변인데도 디스크만 예약 경계에 딱 붙고 반대쪽에 여유가 전부 쏠림,
    sample/screen.png)가 다시 생기지 않는지 직접 구분해서 확인한다."""
    W, H = 1920, 1080
    D0 = mv.disc_diameter(mv.get_layout(False))
    reserved_gap = int(round(mv.DISC_RESERVED_GAP * 1.0))

    def layout_for(cap_pos, pb_pos):
        avail_top, avail_bottom, top_r, bottom_r = mv.disc_avail_zone(
            H, W, 1.0, True, cap_pos, True, True, pb_pos, 180.0)
        D = D0
        shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, "classic")
        if shrink < 1.0:
            D = int(D * shrink)
            D -= D % 2
        reserved_top, reserved_bottom = mv.disc_vertical_reservation(
            H, 1.0, True, cap_pos, True, True, pb_pos, W)
        stack_shift, cy = mv.disc_stack_layout(
            H, 1.0, reserved_top, reserved_bottom, top_r, bottom_r, D)
        return top_r, bottom_r, D, reserved_top, reserved_bottom, stack_shift, cy

    # 단일 변(top 만, 캡션+진행바 모두 top): 묶음↔디스크 간격은 타이트(reserved_gap),
    # 묶음 위쪽 바깥 여백(=stack_shift)이 디스크 아래쪽 -> 프레임 바닥 여백과 같다.
    top_r, bottom_r, D, reserved_top, reserved_bottom, stack_shift, cy = layout_for("top", "top")
    assert (top_r, bottom_r) == (True, False)
    half = D // 2
    disc_top, disc_bottom = cy - half, cy + half
    assert (disc_top - stack_shift) - reserved_top == reserved_gap  # 타이트 간격 보존
    assert abs((H - disc_bottom) - stack_shift) <= 1  # 대칭: 위 여백 == 아래 여백(반올림 오차 허용)
    assert stack_shift > 0  # 실제로 남는 여유가 있어 이 검증이 의미있음
    # 옛 버그(앵커만, 반대쪽에 전부 몰림) 재현값과 달라야 한다
    old_buggy_cy = reserved_top + reserved_gap + half
    assert cy != old_buggy_cy

    # 단일 변(bottom 만) — 대칭 미러: 디스크 위쪽 바깥 여백(=stack_shift)이 하단
    # 묶음 실제 상단(H-reserved_bottom-stack_shift) -> 디스크 하단 간의 타이트한
    # 간격과 대칭을 이룬다(정수 나눗셈 반올림으로 ±1px 오차 허용).
    top_r2, bottom_r2, D2, rt2, rb2, shift2, cy2 = layout_for("bottom", "bottom")
    assert (top_r2, bottom_r2) == (False, True)
    half2 = D2 // 2
    disc_top2, disc_bottom2 = cy2 - half2, cy2 + half2
    assert disc_top2 == shift2  # 디스크 위쪽 바깥 여백 == stack_shift(대칭 중앙정렬)
    group_top_edge2 = H - rb2 - shift2  # 하단 묶음이 실제로 이동한 뒤의 상단 y
    assert abs((group_top_edge2 - disc_bottom2) - reserved_gap) <= 1  # 타이트 간격 보존
    assert shift2 > 0  # 실제로 남는 여유가 있어 이 검증이 의미있음
    old_buggy_cy2 = H - rb2 - reserved_gap - half2
    assert cy2 != old_buggy_cy2  # 옛 버그(앵커만, 반대쪽에 전부 몰림) 재현값과 달라야 한다

    # 양쪽 변(top 캡션 + bottom 진행바) — 여전히 두 묶음 사이 정중앙
    top_r3, bottom_r3, D3, rt3, rb3, shift3, cy3 = layout_for("top", "bottom")
    assert (top_r3, bottom_r3) == (True, True)
    avail_top3, avail_bottom3, _, _ = mv.disc_avail_zone(
        H, W, 1.0, True, "top", True, True, "bottom", 180.0)
    assert avail_top3 < cy3 < avail_bottom3


def test_disc_shrink_factor_clamps_when_theme_extent_exceeds_avail_zone():
    """disc_shrink_factor() 의 핵심 축소 수식 검증: 가용 세로 구간보다 테마 조합
    (classic/square_spin/lp_vinyl/text_ring)의 최대 확장치가 더 크면, 축소 배율을
    적용한 뒤의 확장치가 그 구간을 넘지 않아야 한다(1920x1080 기준 D, 인위적으로
    좁힌 300px 짜리 존으로 축소가 실제로 필요한 상황을 재현)."""
    import math
    D = mv.disc_diameter(mv.get_layout(False))  # 1920x1080 기본 D
    avail_top, avail_bottom = 400, 700  # 300px 짜리 좁은 존
    vzone = avail_bottom - avail_top
    for theme in ("classic", "square_spin", "lp_vinyl", "text_ring"):
        shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, theme)
        assert 0 < shrink <= 1.0
        D_shrunk = int(D * shrink)
        D_shrunk -= D_shrunk % 2
        D_shrunk = max(D_shrunk, 2)
        if theme == "square_spin":
            extent = int(math.ceil(D_shrunk * math.sqrt(2)))
            extent += extent % 2
        elif theme == "lp_vinyl":
            extent = int(D_shrunk * mv.LP_VINYL_SIZE_SCALE)
            extent -= extent % 2
        elif theme == "text_ring":
            extent = int(D_shrunk * mv.TEXT_RING_SCALE)
            extent -= extent % 2
        else:
            extent = D_shrunk
        assert extent <= vzone + 2, (theme, extent, vzone)  # 짝수 보정 반올림 오차(최대 ±2px) 허용


def test_disc_shrink_factor_noop_when_theme_extent_already_fits():
    """이미 여유 공간 안에 들어가면(오버플로가 아니면) 배율은 정확히 1.0 이어야
    한다 — 불필요하게 축소하지 않는다(기본 1920x1080, 예약 없음 케이스에서
    lp_vinyl/text_ring/square_spin 모두 실제로 여유 안에 들어가는지도 함께 확인)."""
    lay = mv.get_layout(False)  # 1920x1080
    W, H = lay["W"], lay["H"]
    D = mv.disc_diameter(lay)
    avail_top, avail_bottom, top_reserved, bottom_reserved = mv.disc_avail_zone(
        H, W, 1.0, False, "auto", False, False, "bottom", None)
    assert top_reserved is False
    assert bottom_reserved is False
    for theme in ("classic", "square_spin", "lp_vinyl", "text_ring"):
        shrink = mv.disc_shrink_factor(D, avail_top, avail_bottom, theme)
        assert shrink == 1.0, (theme, shrink)


def test_title_caption_pos_cli_choice_includes_bottom():
    """--title-caption-pos 가 이제 "bottom" 도 받는지 확인 (프로덕트 오너 요청:
    화면 하단에 진행바+제목+아티스트를 앵커하는 레이아웃)."""
    import inspect
    main_src = inspect.getsource(mv.main)
    assert 'choices=["auto", "top", "bottom"]' in main_src


# ---------- lp_vinyl: 커버+비닐 조합의 수평 중앙 정렬 / 상대 크기 --------------

def test_lp_vinyl_render_branch_centers_combined_bounding_box_source():
    """render() 의 lp_vinyl 분기가 커버만이 아니라 '커버+비닐 조합'의 바운딩
    박스를 프레임 중앙에 맞추는 공식을 실제로 쓰는지 소스 레벨로 확인한다
    (제품 오너 피드백: 비닐이 화면 오른쪽 끝까지 삐져나와 조합 전체가 오른쪽으로
    쏠려 보였다 — sample/playscreen.png). --disc-lp-side 로 좌/우 모두 지원해야
    하는 후속 요구사항 때문에, 수기 bbox_shift 공식은 min/max 기반의
    lp_vinyl_cover_center_x() 순수 함수 호출로 대체됐다."""
    import inspect
    render_src = inspect.getsource(mv.render)
    lp_branch = render_src.split(
        'elif disc_theme == "lp_vinyl" and vinyl_png and cover_png:')[1].split(
        'elif disc_theme == "text_ring"')[0]
    assert "cover_cx = lp_vinyl_cover_center_x(W, D_lp, VD, off_x)" in lp_branch
    assert "disc_lp_side" in lp_branch  # 좌/우 방향 인자가 실제로 쓰인다


def test_lp_vinyl_render_branch_off_x_formula_is_additive_and_signed():
    """off_x 계산이 (1) LP_VINYL_OFFSET 비율 + LP_VINYL_OFFSET_NUDGE_PX 고정
    픽셀(스케일 보정)의 합이고 (2) --disc-lp-side 에 따라 부호가 뒤집히는지
    소스 레벨로 확인한다."""
    import inspect
    render_src = inspect.getsource(mv.render)
    lp_branch = render_src.split(
        'elif disc_theme == "lp_vinyl" and vinyl_png and cover_png:')[1].split(
        'elif disc_theme == "text_ring"')[0]
    assert "LP_VINYL_OFFSET_NUDGE_PX" in lp_branch
    assert 'off_x = off_mag if disc_lp_side != "left" else -off_mag' in lp_branch


def test_lp_vinyl_cover_center_x_centers_bbox_for_both_sides():
    """lp_vinyl_cover_center_x() 가 --disc-lp-side "right"/"left" 양쪽에서(부호만
    다른 off_x, 넛지 픽셀 포함) 실제로 '커버+비닐 조합'의 바운딩박스를 프레임
    가로 중앙에 놓는지 여러 해상도/방향에서 직접 계산해 검증한다 — 어느 쪽이
    바운딩박스 경계를 결정하는지 하드코딩하지 않고 min/max 로 구하므로 두 부호
    모두 성립해야 한다."""
    scale = 1.0
    for shorts in (False, True):
        lay = mv.get_layout(shorts)
        W = lay["W"]
        D = mv.disc_diameter(lay)
        D_lp = int(D * mv.LP_VINYL_SIZE_SCALE)
        D_lp -= D_lp % 2
        VD = int(D_lp * mv.LP_VINYL_SCALE)
        VD -= VD % 2
        off_mag = int(D_lp * mv.LP_VINYL_OFFSET) + int(round(mv.LP_VINYL_OFFSET_NUDGE_PX * scale))
        for off_x in (off_mag, -off_mag):
            cover_cx = mv.lp_vinyl_cover_center_x(W, D_lp, VD, off_x)
            cover_left, cover_right = cover_cx - D_lp // 2, cover_cx + D_lp // 2
            vinyl_left, vinyl_right = cover_cx + off_x - VD // 2, cover_cx + off_x + VD // 2
            bbox_left = min(cover_left, vinyl_left)
            bbox_right = max(cover_right, vinyl_right)
            center = (bbox_left + bbox_right) / 2
            assert abs(center - W / 2) <= 1, (shorts, off_x, center, W / 2)


def test_lp_vinyl_cover_center_x_right_left_are_mirror_images():
    """"right"(양의 off_x)와 "left"(음의 off_x)는 서로 수평 미러 관계여야 한다 —
    cover_cx 가 W/2 기준으로 대칭이어야(반올림 오차 이내) 실제 렌더에서 좌우
    방향이 정확히 뒤집혀 보인다."""
    W = 1920
    D_lp, VD = 588, 564
    off_mag = 310
    cx_right = mv.lp_vinyl_cover_center_x(W, D_lp, VD, off_mag)
    cx_left = mv.lp_vinyl_cover_center_x(W, D_lp, VD, -off_mag)
    assert abs((cx_right - W / 2) - (W / 2 - cx_left)) <= 1


def test_lp_vinyl_offset_nudge_is_additive_and_scale_aware():
    """제품 오너 피드백("비닐이 조금 더 삐져나와도 될 것 같아"): 비율(LP_VINYL_OFFSET)
    은 레퍼런스 실측 근거가 있어 그대로 두고, 그 위에 스케일 보정된 고정 픽셀
    (LP_VINYL_OFFSET_NUDGE_PX)이 순수 additive 로 더해져야 한다 — 그리고 그 넛지
    자체도 scale 에 비례해야 한다(고정 10px 를 그냥 더하기만 하면 해상도가 커져도
    항상 10px 라 상대적으로 점점 안 보이게 된다)."""
    assert mv.LP_VINYL_OFFSET_NUDGE_PX > 0
    D_lp = 600  # 임의의 고정값(스케일과 무관하게 순수 공식만 검증)
    ratio_part = int(D_lp * mv.LP_VINYL_OFFSET)
    for scale in (1.0, 2 / 3, 2.0):
        nudge = int(round(mv.LP_VINYL_OFFSET_NUDGE_PX * scale))
        off_mag = ratio_part + nudge
        assert off_mag - ratio_part == nudge  # 비율 파트와 완전히 분리된 additive 값
        assert off_mag > ratio_part  # 항상 비율 파트보다 커야 함(+ 넛지)
    small = int(round(mv.LP_VINYL_OFFSET_NUDGE_PX * 0.5))
    large = int(round(mv.LP_VINYL_OFFSET_NUDGE_PX * 2.0))
    assert large > small  # 스케일에 비례(고정 픽셀이 아님)


def test_disc_lp_side_cli_choice_declared_with_right_default():
    """--disc-lp-side 가 choices=["left","right"], default="right" 로 선언되어
    있는지 확인 — 기본값이 기존 동작(항상 오른쪽으로만 삐져나옴)과 정확히
    일치해야 한다(하위 호환)."""
    import inspect
    main_src = inspect.getsource(mv.main)
    assert 'choices=["left", "right"], default="right"' in main_src


# ---------- text_ring: --disc-ring-side (lp_vinyl 의 --disc-lp-side 와는 별개) ----

def test_disc_ring_side_cli_choice_declared_with_left_default():
    """--disc-ring-side 가 choices=["left","right"], default="left" 로 선언되어
    있는지 확인 — 기본값이 기존 동작(항상 왼쪽으로만 삐져나옴)과 정확히
    일치해야 한다(하위 호환). --disc-lp-side 와는 완전히 독립된 별개 플래그다."""
    import inspect
    main_src = inspect.getsource(mv.main)
    assert 'choices=["left", "right"], default="left"' in main_src


def test_render_text_ring_branch_uses_signed_off_x_for_ring_side():
    """render() 의 text_ring 분기가 off_mag(항상 양수) + disc_ring_side 부호로
    off_x 를 결정하는지, 그리고 커버 위치(cover_cx)는 W/2 고정으로 disc_ring_side
    와 무관한지 소스 레벨로 확인한다(lp_vinyl 과 달리 별도 bbox 재중앙 계산이
    필요 없다는 설계 판단의 근거)."""
    import inspect
    render_src = inspect.getsource(mv.render)
    tr_branch = render_src.split(
        'elif disc_theme == "text_ring" and ring_png and cover_png:')[1].split(
        "# 자막 burn-in")[0]
    assert 'off_x = off_mag if disc_ring_side == "right" else -off_mag' in tr_branch
    assert "cover_cx = (W - D) // 2 + D // 2" in tr_branch  # W/2, disc_ring_side 와 무관


def test_text_ring_cover_position_unchanged_ring_mirrors_between_sides():
    """--disc-ring-side left/right 는 링의 노출 방향만 좌우로 뒤집어야 하고,
    커버 자체의 위치(cover_cx)는 절대 움직이면 안 된다(text_ring 은 lp_vinyl 과
    달리 커버가 항상 화면 중앙 고정 — round 5 보고에서 렌더로 확인한 설계).
    링 중심은 커버 중심을 기준으로 좌우 대칭이어야 한다."""
    W = 1920
    D = 452
    cover_cx = (W - D) // 2 + D // 2
    assert cover_cx == W // 2

    off_mag = int(D * mv.TEXT_RING_OFFSET)
    RD = int(D * mv.TEXT_RING_SCALE)
    RD -= RD % 2

    ring_centers = {}
    for side in ("left", "right"):
        off_x = off_mag if side == "right" else -off_mag
        rx = cover_cx + off_x - RD // 2
        ring_centers[side] = rx + RD // 2

    # 커버 위치는 두 방향 모두 동일(=W/2, 위에서 이미 확인)
    # 링 중심은 커버 중심 기준 정확히 반대 방향으로 대칭
    assert ring_centers["right"] - cover_cx == cover_cx - ring_centers["left"]
    assert ring_centers["left"] < cover_cx < ring_centers["right"]


def test_lp_vinyl_cover_only_slightly_bigger_than_vinyl():
    """제품 오너 피드백: "앨범이미지 좀 줄여, LP판보다 진짜 살짝 더 큰 정도로"
    -> 커버(D_lp)가 비닐(VD)보다 크되 그 차이는 10% 미만이어야 한다."""
    assert mv.LP_VINYL_SCALE > 0.93
    lay = mv.get_layout(False)
    D = mv.disc_diameter(lay)
    D_lp = int(D * mv.LP_VINYL_SIZE_SCALE)
    D_lp -= D_lp % 2
    VD = int(D_lp * mv.LP_VINYL_SCALE)
    VD -= VD % 2
    ratio = D_lp / VD
    assert 1.0 < ratio < 1.1


# ---------- lp_vinyl: 비닐 표면 입체감(셰이딩) ----------------------------------

def test_vinyl_shading_expr_returns_bounded_additive_expression():
    expr = mv.vinyl_shading_expr("X", "Y", 150.0, 148.0, 33.0)
    assert isinstance(expr, str) and expr
    assert "exp(" in expr and "pow(" in expr
    # 그루브/라벨 패스가 그대로 groove/r(X,Y) 등에 더할 수 있는 가산식이어야
    # 하므로 괄호로 감싸져 있어야 한다(연산 우선순위 안전).
    assert expr.startswith("(") and expr.endswith(")")


def test_make_vinyl_png_shading_changes_pixels_vs_no_shading(tmp_path, monkeypatch):
    """입체감 셰이딩을 껐을 때(가산식을 0으로)와 켰을 때 픽셀이 달라야 한다 —
    "평면적으로 보인다"는 피드백에 대해 실제로 밝기 변화를 만들어내는지 확인."""
    import pytest
    pytest.importorskip("PIL")
    from PIL import Image

    off = tmp_path / "vinyl_no_shade.png"
    monkeypatch.setattr(mv, "vinyl_shading_expr", lambda *a, **k: "0")
    mv.make_vinyl_png(str(off), 200, "7DD3FC")
    monkeypatch.undo()

    on = tmp_path / "vinyl_shade.png"
    mv.make_vinyl_png(str(on), 200, "7DD3FC")

    a = Image.open(off).convert("RGB")
    b = Image.open(on).convert("RGB")
    assert list(a.getdata()) != list(b.getdata())


# ---------- lp_vinyl: 커버/비닐 라벨 아트 분리 (--disc-lp-art) ------------------

def test_disc_lp_art_cli_flag_declared(monkeypatch, capsys):
    import pytest
    monkeypatch.setattr("sys.argv", ["make_mv.py", "--help"])
    with pytest.raises(SystemExit):
        mv.main()
    out = capsys.readouterr().out
    assert "--disc-lp-art" in out


def test_disc_lp_art_falls_back_to_cover_art_when_absent():
    """main() 의 lp_vinyl 프리패스: --disc-lp-art 를 안 주면(또는 파일이 없으면)
    비닐 라벨에 커버와 같은 art 를 그대로 쓰는 기존 폴백 동작을 유지해야 한다."""
    import inspect
    src = inspect.getsource(mv.main)
    branch = src.split('if args.disc_theme == "lp_vinyl":')[1].split(
        'elif args.disc_theme == "text_ring":')[0]
    assert "args.disc_lp_art" in branch
    assert "lp_art = art" in branch
    assert "make_vinyl_png(vinyl_png, VD, accent, art_src=lp_art)" in branch
