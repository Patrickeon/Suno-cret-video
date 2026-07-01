"""쇼츠용 하이라이트(후렴) 구간 자동 감지.

ffmpeg astats 로 0.5초 창마다 RMS 레벨(dB)을 뽑아, clip_len 창의 평균 레벨이 가장 높은
지점들을 (서로 겹치지 않게) 고른다. 후렴은 보통 가장 크고 꽉 찬 구간이라 이 휴리스틱으로
꽤 잘 잡힌다. ffmpeg 만 사용(추가 의존성 없음)."""
import bisect
import re
import subprocess

_PTS = re.compile(r"pts_time:([\d.]+)")
_RMS = re.compile(r"RMS_level=(-?[\d.]+|-?inf|nan)")
_WINDOW_SAMPLES = 22050  # ~0.5초 창 (44.1k 기준; 다른 SR이어도 충분히 촘촘)


def momentary_loudness(audio):
    """[(t_sec, rms_db), ...] 시계열. 무음(-inf/nan)은 제외.
    (함수명은 호환을 위해 유지 — 실제로는 창별 RMS 레벨)"""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", audio, "-af",
         f"asetnsamples={_WINDOW_SAMPLES}:p=0,astats=metadata=1:reset=1,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    pts = []
    cur_t = None
    for line in out.splitlines():
        m = _PTS.search(line)
        if m:
            cur_t = float(m.group(1))
            continue
        r = _RMS.search(line)
        if r and cur_t is not None:
            v = r.group(1)
            if v not in ("-inf", "nan"):
                pts.append((cur_t, float(v)))
            cur_t = None
    return pts


def detect_peaks(audio, n=3, clip_len=30.0, min_gap=20.0, step=2.0):
    """평균 라우드니스가 높은 clip_len 창의 시작 시각 리스트(최대 n개, 시간순).
    감지 실패 시 빈 리스트."""
    pts = momentary_loudness(audio)
    if not pts:
        return []
    times = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    dur = times[-1]

    cand = []
    t = 0.0
    while t + clip_len <= max(dur, clip_len):
        lo = bisect.bisect_left(times, t)
        hi = bisect.bisect_left(times, t + clip_len)
        seg = vals[lo:hi]
        if seg:
            cand.append((sum(seg) / len(seg), t))
        t += step
    cand.sort(reverse=True)  # 라우드니스 높은 순

    starts = []
    for _avg, st in cand:
        if all(abs(st - s) >= min_gap for s in starts):
            starts.append(st)
            if len(starts) >= n:
                break
    starts.sort()
    return starts
