"""후렴 감지 — momentary_loudness 를 합성 데이터로 대체해 선택 로직 검증(ffmpeg 불필요)."""
import highlights


def _fake_curve():
    # 0~60s, 30~40s 구간이 가장 큰 라우드니스(후렴)라고 가정
    pts = []
    t = 0.0
    while t <= 60.0:
        m = -14.0 if 30.0 <= t <= 40.0 else -24.0
        pts.append((t, m))
        t += 0.5
    return pts


def test_detect_peaks_picks_loudest(monkeypatch):
    monkeypatch.setattr(highlights, "momentary_loudness", lambda a: _fake_curve())
    starts = highlights.detect_peaks("x.mp3", n=1, clip_len=10.0, step=2.0)
    assert len(starts) == 1
    # 가장 시끄러운 30~40s 창이 잡혀야 함
    assert 26.0 <= starts[0] <= 34.0


def test_detect_peaks_respects_gap_and_count(monkeypatch):
    monkeypatch.setattr(highlights, "momentary_loudness", lambda a: _fake_curve())
    starts = highlights.detect_peaks("x.mp3", n=3, clip_len=8.0, min_gap=15.0)
    assert len(starts) <= 3
    assert starts == sorted(starts)
    for i in range(1, len(starts)):
        assert starts[i] - starts[i - 1] >= 15.0


def test_detect_peaks_empty_when_no_data(monkeypatch):
    monkeypatch.setattr(highlights, "momentary_loudness", lambda a: [])
    assert highlights.detect_peaks("x.mp3") == []
