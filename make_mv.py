#!/usr/bin/env python3
"""
make_mv.py - 음원 + 가사 -> 유튜브 뮤직비디오 자동 생성

기능:
  - ffmpeg 비주얼라이저(파형/스펙트럼) + 가사 자막 burn-in
  - 배경 이미지 켄 번스(줌/팬) + 다중 이미지 크로스페이드
  - 가로 1080p 롱폼 / 세로 9:16 쇼츠(클라이맥스 구간만) 출력
  - 썸네일(1280x720) 자동 생성 + 워터마크/로고 오버레이
  - 가사 싱크: .lrc(정확) / .txt 균등분배(초안) / --align auto(강제정렬)

필요: Python 3.8+, ffmpeg / ffprobe (PATH). 표준 라이브러리만으로 동작.
      --align auto 만 추가로 stable-ts(+torch) 필요 (requirements-align.txt).

예시:
  # 롱폼
  python make_mv.py --audio song.mp3 --lyrics song.lrc --bg art.jpg \
      --title "곡 제목" --artist "아티스트" --watermark "@내채널" --out mv.mp4
  # 쇼츠 (1분 5초부터 30초 클라이맥스)
  python make_mv.py --audio song.mp3 --lyrics song.lrc --bg art.jpg \
      --shorts --clip-start 1:05 --clip-len 30 --out short.mp4
  # txt 가사 자동 정렬 -> 초안 LRC 만 추출
  python make_mv.py --audio song.mp3 --lyrics song.txt --align auto --lrc-out draft.lrc
"""

import argparse
import json
import os
import re
import subprocess
import sys

FPS = 30
# 폰트 패밀리명. 기본은 Windows의 Malgun Gothic, 컨테이너(Linux)에선 MV_FONT 로 교체
# (예: 도커에서 NanumGothic). drawtext/libass 모두 fontconfig 패밀리명으로 해석.
_DEFAULT_FONT = os.environ.get("MV_FONT", "Malgun Gothic")
DRAW_FONT = _DEFAULT_FONT   # drawtext(워터마크/썸네일)용
SUB_FONT = _DEFAULT_FONT    # libass(자막)용

# ---------- ffmpeg helpers ----------

def run(cmd, **kw):
    return subprocess.run(cmd, **kw)

def run_ffmpeg_progress(cmd, work_dir, duration):
    """ffmpeg 를 -progress 로 돌리며 진행률을 'MV_PROGRESS <pct>' 로 stdout 출력.
    반환: (returncode, stderr_text). 진행률을 모르는 호출(썸네일 등)엔 쓰지 않는다."""
    cmd = cmd + ["-progress", "pipe:1", "-nostats", "-loglevel", "error"]
    proc = subprocess.Popen(
        cmd, cwd=work_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    last = -1
    for line in proc.stdout:
        # ffmpeg progress 블록의 out_time_ms 값은 마이크로초 단위다.
        if line.startswith("out_time_ms="):
            try:
                sec = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            pct = int(min(99, max(0, sec / duration * 100))) if duration else 0
            if pct != last:
                last = pct
                print(f"MV_PROGRESS {pct}", flush=True)
    proc.wait()
    err = proc.stderr.read() if proc.stderr else ""
    return proc.returncode, err

def probe_duration(audio):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", audio,
    ])
    return float(json.loads(out)["format"]["duration"])

def parse_time(s):
    """'1:05' 또는 '65' 또는 '1:05.5' -> 초(float)"""
    s = str(s).strip()
    if ":" in s:
        parts = s.split(":")
        parts = [float(p) for p in parts]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return float(s)

# ---------- 레이아웃 (해상도/방향) ----------

def get_layout(shorts, scale=1.0):
    """방향별 기준 레이아웃을 scale 배로 키운다 (1.0=1080 기준, 1.333=1440p, 2.0=4K).
    폰트·여백·비주얼라이저 높이가 함께 커져 비율이 유지된다."""
    def s(v):
        # 짝수로 (yuv420p·showcqt 등은 홀수 치수에서 깨짐)
        n = int(round(v * scale))
        return n - (n % 2)
    if shorts:
        return dict(
            W=s(1080), H=s(1920), viz_h=s(320), viz_y=f"H-h-{s(140)}",
            font_size=s(78), margin_v=s(820), margin_lr=s(90),
        )
    return dict(
        W=s(1920), H=s(1080), viz_h=s(260), viz_y=f"H-h-{s(50)}",
        font_size=s(72), margin_v=s(360), margin_lr=s(120),
    )

# ---------- 가사 파싱 ----------

LRC_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")

def parse_lrc(path):
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = LRC_RE.match(line.strip())
            if not m:
                continue
            mm, ss, text = m.group(1), m.group(2), m.group(3).strip()
            t = int(mm) * 60 + float(ss)
            if text:
                items.append((t, text))
    items.sort(key=lambda x: x[0])
    return items

def read_txt_lines(path):
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]

def even_distribute(lines, duration, intro=0.0, outro=0.0):
    span = max(1.0, duration - intro - outro)
    n = max(1, len(lines))
    seg = span / n
    return [(intro + i * seg, intro + (i + 1) * seg, t) for i, t in enumerate(lines)]

def lrc_to_cues(items, duration):
    cues = []
    for i, (start, text) in enumerate(items):
        end = items[i + 1][0] if i + 1 < len(items) else duration
        cues.append((start, end, text))
    return cues

def slice_cues_for_clip(cues, start, length):
    """[start, start+length] 구간으로 잘라내고 시간을 -start 시프트."""
    end = start + length
    out = []
    for s, e, text in cues:
        if e <= start or s >= end:
            continue
        ns = max(0.0, s - start)
        ne = min(length, e - start)
        if ne > ns:
            out.append((ns, ne, text))
    return out

# ---------- 강제 정렬 (stable-ts, 소프트 임포트) ----------

def align_with_stable_ts(audio, lyrics_text, model_name="base"):
    """알려진 가사 텍스트를 오디오에 강제 정렬 -> [(start, end, text), ...] (줄 단위)."""
    try:
        import stable_whisper  # noqa
    except ImportError:
        sys.exit(
            "--align auto 에는 stable-ts 가 필요합니다.\n"
            "  pip install -r requirements.txt\n"
            "설치 없이 쓰려면 --lyrics 를 .lrc 로 주거나 균등분배(.txt)를 사용하세요."
        )
    print(f"[align] stable-ts 모델 로드: {model_name} (CPU면 시간이 걸립니다)")
    model = stable_whisper.load_model(model_name)
    result = model.align(audio, lyrics_text, language=None)
    cues = []
    for seg in result.segments:
        text = seg.text.strip()
        if text:
            cues.append((float(seg.start), float(seg.end), text))
    return cues

# ---------- 자막(.ass) / LRC 출력 ----------

def fmt_lrc_time(t):
    m = int(t // 60)
    return f"[{m:02d}:{t - m * 60:05.2f}]"

def write_lrc(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for start, _e, text in cues:
            f.write(f"{fmt_lrc_time(start)}{text}\n")

def fmt_ass_time(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    return f"{h:d}:{m:02d}:{t % 60:05.2f}"

def ass_escape(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyric,{font},{fontsize},{primary},&H000088FF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,4,2,{align},{mlr},{mlr},{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def hex_to_ass(color):
    """'RRGGBB' 또는 '#RRGGBB' -> ASS PrimaryColour '&H00BBGGRR'. 잘못되면 흰색."""
    c = str(color).strip().lstrip("#")
    if len(c) != 6:
        c = "FFFFFF"
    try:
        int(c, 16)
    except ValueError:
        c = "FFFFFF"
    return f"&H00{c[4:6]}{c[2:4]}{c[0:2]}".upper()


def write_ass(cues, path, lay, font=SUB_FONT, color="FFFFFF", size_mult=1.0,
              pos="bottom"):
    fontsize = max(1, int(round(lay["font_size"] * float(size_mult))))
    align = {"bottom": 2, "middle": 5, "top": 8}.get(pos, 2)
    if pos == "top":
        marginv = int(lay["H"] * 0.08)
    elif pos == "middle":
        marginv = 10  # 세로 중앙 정렬은 MarginV 영향 작음
    else:
        marginv = lay["margin_v"]
    with open(path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER.format(
            W=lay["W"], H=lay["H"], font=font, fontsize=fontsize,
            mlr=lay["margin_lr"], marginv=marginv,
            primary=hex_to_ass(color), align=align,
        ))
        for start, end, text in cues:
            if end <= start:
                end = start + 0.5
            f.write(
                f"Dialogue: 0,{fmt_ass_time(start)},{fmt_ass_time(end)},"
                f"Lyric,,0,0,0,,{ass_escape(text)}\n"
            )

# ---------- 필터 빌더 ----------

def build_bg(bg_list, lay, duration, kenburns, bg_color, video_bg=None):
    """
    배경 비디오 체인 빌드.
    반환: (extra_inputs, filter_parts, bg_label, audio_idx)
      extra_inputs: 배경 입력 -i 인자 리스트(앞쪽). audio_idx = 배경 입력 개수.
    우선순위: video_bg(영상) > bg_list(이미지) > 단색.
    """
    W, H = lay["W"], lay["H"]

    # 영상 배경 (AI 생성 클립 등): 무한 루프로 곡 길이를 덮고 W×H 로 cover-crop
    if video_bg:
        inputs = ["-stream_loop", "-1", "-i", os.path.abspath(video_bg)]
        parts = [
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={FPS}[bg]"
        ]
        return inputs, parts, "[bg]", 1

    if not bg_list:
        return [], [f"color=c={bg_color}:s={W}x{H}:r={FPS}[bg]"], "[bg]", 0

    inputs = []
    parts = []
    n = len(bg_list)

    if n == 1:
        inputs += ["-loop", "1", "-i", os.path.abspath(bg_list[0])]
        if kenburns:
            frames = max(1, round(duration * FPS))
            parts.append(
                f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                f"crop={W*2}:{H*2},"
                f"zoompan=z='min(zoom+0.0005,1.4)':d={frames}:s={W}x{H}:fps={FPS},"
                f"setsar=1[bg]"
            )
        else:
            parts.append(
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1[bg]"
            )
        return inputs, parts, "[bg]", 1

    # 다중 이미지: 각 L초씩 zoompan 후 xfade 크로스페이드
    fade = 1.0
    L = (duration + (n - 1) * fade) / n  # 각 클립 길이
    seg_frames = max(1, round(L * FPS))
    for i, img in enumerate(bg_list):
        inputs += ["-loop", "1", "-t", f"{L:.3f}", "-i", os.path.abspath(img)]
        if kenburns:
            parts.append(
                f"[{i}:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                f"crop={W*2}:{H*2},"
                f"zoompan=z='min(zoom+0.0006,1.4)':d={seg_frames}:s={W}x{H}:fps={FPS},"
                f"setsar=1[b{i}]"
            )
        else:
            parts.append(
                f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1,fps={FPS}[b{i}]"
            )
    prev = "b0"
    for i in range(1, n):
        offset = i * (L - fade)
        out_lbl = "bg" if i == n - 1 else f"x{i}"
        parts.append(
            f"[{prev}][b{i}]xfade=transition=fade:duration={fade}:"
            f"offset={offset:.3f}[{out_lbl}]"
        )
        prev = out_lbl
    return inputs, parts, "[bg]", n

def build_viz(audio_spec, lay, viz):
    """비주얼라이저 체인. 반환: (parts, viz_label or None)"""
    W = lay["W"]
    h = lay["viz_h"]
    if viz == "none":
        return [], None
    if viz == "waves":
        return [f"[{audio_spec}]showwaves=s={W}x{h}:mode=cline:"
                f"colors=white@0.85:rate={FPS},format=yuva420p[viz]"], "[viz]"
    if viz == "cqt":
        return [f"[{audio_spec}]showcqt=s={W}x{h}:count=2:gamma=4,"
                "format=yuva420p[viz]"], "[viz]"
    if viz == "spectrum":
        return [f"[{audio_spec}]showspectrum=s={W}x{h}:mode=combined:"
                "color=intensity:scale=cbrt:slide=scroll,format=yuva420p[viz]"], "[viz]"
    if viz == "bars":
        # 주파수 막대그래프 (음악에 반응) — 컬러풀하고 선명해 가사 영상에 잘 맞음
        return [f"[{audio_spec}]showfreqs=s={W}x{h}:mode=bar:ascale=log:"
                f"fscale=log:win_size=2048:colors=0x6d28d9|0xec4899:rate={FPS},"
                "format=yuva420p[viz]"], "[viz]"
    return [], None

# ---------- 텍스트 파일(drawtext용) ----------

def write_textfile(text, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

# ---------- 렌더 ----------

def render(audio, ass_path, out, lay, bg_list=None, viz="waves",
           bg_color="0x0a0a14", duration=None, kenburns=True,
           clip_start=None, clip_len=None, watermark=None, logo=None,
           video_bg=None, crf=20, scale=1.0,
           normalize=False, fade_in=0.0, fade_out=0.0,
           vignette=False, grain=False):
    work_dir = os.path.dirname(os.path.abspath(ass_path)) or "."
    ass_name = os.path.basename(ass_path)
    W, H = lay["W"], lay["H"]

    extra_inputs, bg_parts, bg_label, audio_idx = build_bg(
        bg_list, lay, duration, kenburns, bg_color, video_bg=video_bg)
    audio_spec = f"{audio_idx}:a"

    parts = list(bg_parts)

    # ---- 오디오 필터 체인 (loudnorm / 페이드) ----
    # 유튜브 기준 -14 LUFS 정규화 + 인트로/아웃트로 페이드.
    afilters = []
    if normalize:
        afilters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    if fade_in and fade_in > 0:
        afilters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out and fade_out > 0 and duration:
        afilters.append(f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}")

    # 비주얼라이저도 오디오 입력을 쓰므로, 필터가 있으면 asplit 으로 나눠 공급한다.
    viz_audio = audio_spec
    if afilters and viz != "none":
        parts.append(f"[{audio_spec}]asplit=2[av][ao]")
        viz_audio = "av"
        parts.append(f"[ao]{','.join(afilters)}[amain]")
        audio_map = "[amain]"
    elif afilters:
        parts.append(f"[{audio_spec}]{','.join(afilters)}[amain]")
        audio_map = "[amain]"
    else:
        audio_map = audio_spec

    viz_parts, viz_label = build_viz(viz_audio, lay, viz)
    parts += list(viz_parts)

    if viz_label:
        parts.append(f"{bg_label}{viz_label}overlay=0:{lay['viz_y']}:"
                     "format=auto[vmix]")
        cur = "[vmix]"
    else:
        cur = bg_label

    # 자막 burn-in
    parts.append(f"{cur}subtitles={ass_name}[vsub]")
    cur = "[vsub]"

    # 워터마크 / 로고 (해상도 scale 에 맞춰 크기/여백 조정)
    wm_fs = int(round(36 * scale))
    pad = int(round(40 * scale))
    logo_idx = None
    if logo:
        logo_idx = audio_idx + 1  # 오디오 다음 입력
        parts.append(f"{cur}[{logo_idx}:v]overlay=W-w-{pad}:H-h-{pad}[vout]")
        cur = "[vout]"
    elif watermark:
        wm_file = "_wm.txt"
        write_textfile(watermark, os.path.join(work_dir, wm_file))
        parts.append(
            f"{cur}drawtext=font={DRAW_FONT}:textfile={wm_file}:"
            f"fontcolor=white@0.55:fontsize={wm_fs}:x=w-tw-{pad}:y=h-th-{int(round(30*scale))}:"
            "shadowcolor=black@0.6:shadowx=2:shadowy=2[vout]"
        )
        cur = "[vout]"

    # ---- 영상 피니셔 (분위기) : 비네트 -> 필름그레인 -> 페이드 ----
    if vignette:
        parts.append(f"{cur}vignette=PI/4[vvig]")
        cur = "[vvig]"
    if grain:
        parts.append(f"{cur}noise=alls=8:allf=t[vgrain]")
        cur = "[vgrain]"
    vfades = []
    if fade_in and fade_in > 0:
        vfades.append(f"fade=t=in:st=0:d={fade_in:.3f}")
    if fade_out and fade_out > 0 and duration:
        vfades.append(f"fade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}")
    if vfades:
        parts.append(f"{cur}{','.join(vfades)}[vfade]")
        cur = "[vfade]"

    full_filter = ";".join(parts)
    final_v = cur

    # 입력 구성: [배경 이미지들...] [오디오] [로고]
    cmd = ["ffmpeg", "-y"]
    cmd += extra_inputs
    if clip_start is not None:
        cmd += ["-ss", f"{clip_start:.3f}"]
    cmd += ["-i", os.path.abspath(audio)]
    if logo:
        cmd += ["-i", os.path.abspath(logo)]

    cmd += [
        "-filter_complex", full_filter,
        "-map", final_v,
        "-map", audio_map,
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
        "-movflags", "+faststart",
        "-shortest",
    ]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += [os.path.abspath(out)]

    print(f"[ffmpeg] 렌더 시작 ({W}x{H}, {duration:.1f}s)...")
    rc, err = run_ffmpeg_progress(cmd, work_dir, duration)
    if rc != 0:
        sys.stderr.write(err)
        sys.exit("ffmpeg 렌더 실패")
    print("MV_PROGRESS 100", flush=True)
    print(f"[done] {os.path.abspath(out)}")

# ---------- 썸네일 ----------

def make_thumbnail(out_path, title, artist=None, bg=None, bg_color="0x0a0a14"):
    work_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    W, Ht = 1280, 720
    write_textfile(title, os.path.join(work_dir, "_ttl.txt"))
    vf = []
    if bg:
        src = ["-i", os.path.abspath(bg)]
        vf.append(f"scale={W}:{Ht}:force_original_aspect_ratio=increase,crop={W}:{Ht}")
    else:
        src = ["-f", "lavfi", "-i", f"color=c={bg_color}:s={W}x{Ht}"]
    vf.append(f"drawbox=0:0:{W}:{Ht}:color=black@0.4:t=fill")
    vf.append(
        f"drawtext=font={DRAW_FONT}:textfile=_ttl.txt:fontcolor=white:"
        "fontsize=92:x=(w-tw)/2:y=(h-th)/2-40:"
        "shadowcolor=black@0.8:shadowx=3:shadowy=3"
    )
    if artist:
        write_textfile(artist, os.path.join(work_dir, "_art.txt"))
        vf.append(
            f"drawtext=font={DRAW_FONT}:textfile=_art.txt:fontcolor=white@0.85:"
            "fontsize=48:x=(w-tw)/2:y=(h-th)/2+70:"
            "shadowcolor=black@0.8:shadowx=2:shadowy=2"
        )
    cmd = ["ffmpeg", "-y"] + src + ["-vf", ",".join(vf), "-frames:v", "1",
                                    os.path.abspath(out_path)]
    print("[thumb] 썸네일 생성...")
    if run(cmd, cwd=work_dir).returncode != 0:
        sys.exit("썸네일 생성 실패")
    print(f"[done] {os.path.abspath(out_path)}")

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="음원+가사 -> 유튜브 뮤직비디오")
    ap.add_argument("--audio", required=True, help="음원 (mp3/wav/flac)")
    ap.add_argument("--lyrics", help="가사 (.txt 또는 .lrc)")
    ap.add_argument("--bg", nargs="+", help="배경 이미지 (여러 장 가능)")
    ap.add_argument("--video-bg", help="배경 영상 (AI 생성 클립 등, 이미지보다 우선)")
    ap.add_argument("--out", default="mv.mp4", help="출력 mp4")
    ap.add_argument("--viz", default="waves",
                    choices=["waves", "cqt", "spectrum", "bars", "none"])
    ap.add_argument("--bg-color", default="0x0a0a14")
    ap.add_argument("--kenburns", action=argparse.BooleanOptionalAction,
                    default=True, help="배경 줌/팬 (기본 on, --no-kenburns 로 끔)")
    # 가사 싱크
    ap.add_argument("--align", choices=["none", "auto"], default="none",
                    help="auto: stable-ts 로 가사 강제정렬")
    ap.add_argument("--align-model", default="base", help="정렬 모델 (tiny/base/small/medium)")
    ap.add_argument("--intro", type=float, default=0.0, help="txt 균등분배: 첫 가사 전(초)")
    ap.add_argument("--outro", type=float, default=0.0, help="txt 균등분배: 끝 여백(초)")
    ap.add_argument("--lrc-out", help="초안 LRC 만 생성하고 종료")
    ap.add_argument("--font", default=SUB_FONT, help="자막 폰트(한글 지원)")
    ap.add_argument("--sub-color", default="FFFFFF", help="자막 색 (RRGGBB, 기본 흰색)")
    ap.add_argument("--sub-size", type=float, default=1.0, help="자막 크기 배율 (기본 1.0)")
    ap.add_argument("--sub-pos", choices=["bottom", "middle", "top"], default="bottom",
                    help="자막 세로 위치")
    ap.add_argument("--keep-ass", action="store_true")
    # 쇼츠 / 클립
    ap.add_argument("--shorts", action="store_true", help="세로 9:16 (1080x1920)")
    ap.add_argument("--clip-start", help="클립 시작 (초 또는 mm:ss)")
    ap.add_argument("--clip-len", type=float, default=30.0, help="클립 길이(초, 기본 30)")
    # 썸네일 / 워터마크
    ap.add_argument("--title", help="썸네일 제목 (주면 썸네일 생성)")
    ap.add_argument("--artist", help="썸네일 아티스트명")
    ap.add_argument("--thumb-out", help="썸네일 경로 (기본 <out>_thumb.jpg)")
    ap.add_argument("--watermark", help="우하단 워터마크 텍스트")
    ap.add_argument("--logo", help="우하단 로고 PNG (watermark보다 우선)")
    # 유튜브 인코딩 / 오디오 / 분위기
    ap.add_argument("--res", choices=["1080", "1440", "2160"], default="1080",
                    help="출력 세로 해상도. 1440/2160 은 유튜브에서 VP9 코덱을 받아 더 선명")
    ap.add_argument("--fps", type=int, default=30, choices=[24, 30, 60],
                    help="프레임레이트 (60 이면 비주얼라이저가 부드러움)")
    ap.add_argument("--normalize", action="store_true",
                    help="유튜브 기준 -14 LUFS 라우드니스 정규화")
    ap.add_argument("--fade-in", type=float, default=0.0, help="인트로 페이드(초, 영상+오디오)")
    ap.add_argument("--fade-out", type=float, default=0.0, help="아웃트로 페이드(초, 영상+오디오)")
    ap.add_argument("--vignette", action="store_true", help="비네트(가장자리 어둡게)")
    ap.add_argument("--film-grain", action="store_true", help="필름 그레인(노이즈) 질감")
    args = ap.parse_args()

    global FPS
    FPS = args.fps
    scale = {"1080": 1.0, "1440": 4 / 3, "2160": 2.0}[args.res]

    full_dur = probe_duration(args.audio)
    print(f"[info] 곡 길이: {full_dur:.1f}s")

    # 클립 구간 결정
    clip_start = None
    if args.clip_start:
        try:
            clip_start = parse_time(args.clip_start)
        except (ValueError, TypeError):
            sys.exit(f"--clip-start 형식 오류: '{args.clip_start}' (mm:ss 또는 초로 입력)")
    clip_len = None
    if clip_start is not None:
        clip_len = min(args.clip_len, full_dur - clip_start)
    render_dur = clip_len if clip_len is not None else full_dur

    # 가사 -> cues (전체 곡 기준)
    cues = []
    if args.lyrics:
        ext = os.path.splitext(args.lyrics)[1].lower()
        if args.align == "auto":
            lines = read_txt_lines(args.lyrics) if ext != ".lrc" else \
                [t for _, t in parse_lrc(args.lyrics)]
            cues = align_with_stable_ts(args.audio, "\n".join(lines), args.align_model)
            print(f"[info] 강제정렬 {len(cues)}줄")
        elif ext == ".lrc":
            cues = lrc_to_cues(parse_lrc(args.lyrics), full_dur)
            print(f"[info] LRC {len(cues)}줄 (정확한 싱크)")
        else:
            lines = read_txt_lines(args.lyrics)
            cues = even_distribute(lines, full_dur, args.intro, args.outro)
            print(f"[info] TXT {len(lines)}줄 균등분배 (초안)")

    # 초안 LRC 추출
    if args.lrc_out:
        if not cues:
            sys.exit("--lrc-out 에는 --lyrics 가 필요합니다.")
        write_lrc(cues, args.lrc_out)
        print(f"[done] 초안 LRC: {args.lrc_out} (손본 뒤 --lyrics 로 다시 실행)")
        return

    # 클립이면 cues 를 구간으로 시프트
    if clip_start is not None:
        cues = slice_cues_for_clip(cues, clip_start, render_dur)

    lay = get_layout(args.shorts, scale)

    out_dir = os.path.dirname(os.path.abspath(args.out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    ass_path = os.path.join(out_dir, "_sub.ass")
    write_ass(cues, ass_path, lay, font=args.font, color=args.sub_color,
              size_mult=args.sub_size, pos=args.sub_pos)

    render(args.audio, ass_path, args.out, lay,
           bg_list=args.bg, viz=args.viz, bg_color=args.bg_color,
           duration=render_dur, kenburns=args.kenburns,
           clip_start=clip_start, clip_len=clip_len,
           watermark=args.watermark, logo=args.logo,
           video_bg=args.video_bg, scale=scale,
           normalize=args.normalize, fade_in=args.fade_in, fade_out=args.fade_out,
           vignette=args.vignette, grain=args.film_grain)

    # 썸네일
    if args.title:
        thumb = args.thumb_out or (os.path.splitext(args.out)[0] + "_thumb.jpg")
        bg0 = args.bg[0] if args.bg else None
        make_thumbnail(thumb, args.title, args.artist, bg=bg0, bg_color=args.bg_color)

    if not args.keep_ass:
        for tmp in ("_sub.ass", "_wm.txt", "_ttl.txt", "_art.txt"):
            try:
                os.remove(os.path.join(out_dir, tmp))
            except OSError:
                pass

if __name__ == "__main__":
    main()
