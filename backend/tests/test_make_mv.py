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
