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
import hashlib
import json
import os
import re
import subprocess
import sys

# Windows 콘솔/서브프로세스의 cp949 등에서 이모지·특수문자 출력이
# UnicodeEncodeError 로 렌더를 죽이지 않도록 안전하게 재설정.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

FPS = 30
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(ROOT_DIR, "fonts")

# 리포 동봉 폰트 (fonts/, OFL): 시스템 설치 없이 어디서든 동일한 룩.
# 기본은 둥글둥글 귀엽고 가독성 좋은 '주아(Jua)'.
_BUNDLED_FONTS = {
    "Jua": "Jua-Regular.ttf",
    "Gowun Dodum": "GowunDodum-Regular.ttf",
}


def bundled_font_file(family):
    f = _BUNDLED_FONTS.get(family)
    if f:
        p = os.path.join(FONTS_DIR, f)
        if os.path.exists(p):
            return p
    return None


# 폰트 패밀리명. 우선순위: MV_FONT 환경변수 > 동봉 Jua > Malgun Gothic.
# (컨테이너에선 MV_FONT=NanumGothic 등으로 교체 가능. libass 는 fontsdir 로
#  동봉 폰트를 직접 읽으므로 fontconfig 설정이 없어도 된다.)
_DEFAULT_FONT = os.environ.get("MV_FONT") or (
    "Jua" if bundled_font_file("Jua") else "Malgun Gothic")
DRAW_FONT = _DEFAULT_FONT   # drawtext(워터마크/썸네일)용
SUB_FONT = _DEFAULT_FONT    # libass(자막)용

_SYSTEM_FONT_CANDS = [
    "C:/Windows/Fonts/malgun.ttf",              # Windows
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",   # Debian/Ubuntu
    "/usr/share/fonts/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",        # macOS
]


def _resolve_fontfile():
    """drawtext 용 폰트 파일 절대경로. fontconfig 미설정 환경(Windows/컨테이너)에서
    font=패밀리 해석이 실패해 한글이 깨지므로 fontfile 을 직접 지정한다."""
    cands = [os.environ.get("MV_FONTFILE"),
             bundled_font_file(_DEFAULT_FONT)] + _SYSTEM_FONT_CANDS
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def _resolve_symbol_fontfile():
    """♪ 등 기호용 폰트. 동봉 Jua 엔 ♪(U+266A) 글리프가 없어 시스템 폰트를 쓴다."""
    for c in _SYSTEM_FONT_CANDS:
        if os.path.exists(c):
            return c
    return None


DRAW_FONTFILE = _resolve_fontfile()
SYMBOL_FONTFILE = _resolve_symbol_fontfile()


def _fontfile_token(path):
    # filtergraph 에서 Windows 경로 콜론은 작은따옴표+이스케이프해야 파싱된다.
    p = path.replace("\\", "/").replace(":", "\\:")
    return f"fontfile='{p}'"


def draw_font_spec():
    """drawtext 필터의 폰트 지정 토큰. fontfile 우선, 없으면 family."""
    if DRAW_FONTFILE:
        return _fontfile_token(DRAW_FONTFILE)
    return f"font={DRAW_FONT}"


def symbol_font_spec():
    """drawtext 기호(♪)용 폰트 토큰."""
    if SYMBOL_FONTFILE:
        return _fontfile_token(SYMBOL_FONTFILE)
    return draw_font_spec()


def subtitles_filter(ass_name):
    """subtitles 필터 문자열. 동봉 fonts/ 를 libass fontsdir 로 등록한다."""
    f = f"subtitles={ass_name}"
    if os.path.isdir(FONTS_DIR):
        p = FONTS_DIR.replace("\\", "/").replace(":", "\\:")
        f += f":fontsdir='{p}'"
    return f

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

def measure_loudnorm(audio, target_i=-14.0, tp=-1.5, lra=11.0):
    """1차 패스로 라우드니스를 측정해 2-pass loudnorm 파라미터를 얻는다.
    실패 시 None (그러면 single-pass 로 폴백)."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", audio, "-af",
         f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    txt = proc.stderr or ""
    s, e = txt.rfind("{"), txt.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        return json.loads(txt[s:e + 1])
    except ValueError:
        return None

def audio_rms_envelope(audio):
    """0.5초 창마다 RMS 레벨(dB) 시계열 [(t, db), ...]. 오디오 반응 배경용."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", audio, "-af",
         "asetnsamples=22050:p=0,astats=metadata=1:reset=1,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    pts, cur = [], None
    for line in out.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            cur = float(m.group(1))
            continue
        r = re.search(r"RMS_level=(-?[\d.]+|-?inf|nan)", line)
        if r and cur is not None:
            v = r.group(1)
            if v not in ("-inf", "nan"):
                pts.append((cur, float(v)))
            cur = None
    return pts

def loudnorm_filter(audio, two_pass, target_i=-14.0, tp=-1.5, lra=11.0):
    """loudnorm 필터 문자열. two_pass 면 측정값을 넣어 정밀 정규화(linear)."""
    base = f"loudnorm=I={target_i:g}:TP={tp:g}:LRA={lra:g}"
    if not two_pass:
        return base
    m = measure_loudnorm(audio, target_i, tp, lra)
    if not m:
        return base
    try:
        return (base +
                f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                f":offset={m['target_offset']}:linear=true")
    except KeyError:
        return base

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
    with open(path, encoding="utf-8-sig") as f:
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
    with open(path, encoding="utf-8-sig") as f:
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

def align_with_stable_ts(audio, lyrics_text, model_name="base", language="ko"):
    """알려진 가사 텍스트를 오디오에 강제 정렬 -> [(start, end, text), ...] (줄 단위).
    최신 stable-ts 는 align 에 명시적 language 를 요구한다(기본 한국어)."""
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
    # original_split: 입력 텍스트의 줄바꿈을 그대로 자막 구간 경계로 유지
    try:
        result = model.align(audio, lyrics_text, language=language, original_split=True)
    except TypeError:
        result = model.align(audio, lyrics_text, language=language)
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
Style: Lyric,{font},{fontsize},{primary},{secondary},&H00101010,&H80000000,{bold},0,0,0,100,100,0,0,1,3,1,{align},{mlr},{mlr},{marginv},1
{extra_styles}
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


def karaoke_text(text, dur):
    """줄 지속시간(dur초)을 글자 수로 균등 분배해 \\kf 색채움 태그를 붙인다."""
    chars = list(text)
    n = len(chars) or 1
    per = max(1, int(round(dur * 100)) // n)  # 글자당 centiseconds
    out = []
    for c in chars:
        esc = c.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
        out.append(f"{{\\kf{per}}}{esc}")
    return "".join(out)


def write_ass(cues, path, lay, font=SUB_FONT, color="FFFFFF", size_mult=1.0,
              pos="bottom", karaoke=False, glow=False, fade=True, preview=False):
    fontsize = max(1, int(round(lay["font_size"] * float(size_mult))))
    align = {"bottom": 2, "middle": 5, "top": 8}.get(pos, 2)
    if pos == "top":
        marginv = int(lay["H"] * 0.08)
    elif pos == "middle":
        marginv = 10  # 세로 중앙 정렬은 MarginV 영향 작음
    else:
        marginv = lay["margin_v"]
    # 카라오케: 아직 안 부른 글자는 어둡게(Secondary), 부른 글자는 색(Primary)
    secondary = "&H00555555" if karaoke else "&H000088FF"
    # 동봉 라운드 폰트(Jua 등)는 이미 두꺼워 합성 볼드를 빼야 모양이 산다
    bold = 0 if font in _BUNDLED_FONTS else 1

    # 다음 소절 미리보기: 현재 줄 아래 작고 반투명하게 (middle 정렬에선 생략)
    preview = preview and pos != "middle"
    extra_styles = ""
    if preview:
        next_size = max(1, int(round(fontsize * 0.52)))
        gap = int(round(fontsize * 1.5))
        next_mv = marginv + gap if pos == "top" else max(10, marginv - gap)
        next_primary = "&H82" + hex_to_ass(color)[4:]  # 같은 색, ~50% 투명
        extra_styles = (
            f"Style: Next,{font},{next_size},{next_primary},{secondary},"
            f"&H82101010,&H80000000,{bold},0,0,0,100,100,0,0,1,2,0,"
            f"{align},{lay['margin_lr']},{lay['margin_lr']},{next_mv},1\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER.format(
            W=lay["W"], H=lay["H"], font=font, fontsize=fontsize,
            mlr=lay["margin_lr"], marginv=marginv, bold=bold,
            primary=hex_to_ass(color), secondary=secondary, align=align,
            extra_styles=extra_styles,
        ))
        for i, (start, end, text) in enumerate(cues):
            if end <= start:
                end = start + 0.5
            # '||' 는 자막 내 줄바꿈(이중 자막: 원문||번역)으로 처리
            body = (karaoke_text(text, end - start) if karaoke
                    else ass_escape(text).replace("||", "\\N"))
            tags = ""
            if fade:
                # 소절 단위로 스르륵 나타났다 사라지는 페이드
                tags += "\\fad(200,260)"
            if glow:
                tags += "\\blur5"  # 은은한 발광
            if tags:
                body = "{" + tags + "}" + body
            f.write(
                f"Dialogue: 0,{fmt_ass_time(start)},{fmt_ass_time(end)},"
                f"Lyric,,0,0,0,,{body}\n"
            )
            if preview and i + 1 < len(cues):
                nxt = ass_escape(cues[i + 1][2]).replace("||", "\\N")
                ntags = "{\\fad(200,200)}" if fade else ""
                f.write(
                    f"Dialogue: 0,{fmt_ass_time(start)},{fmt_ass_time(end)},"
                    f"Next,,0,0,0,,{ntags}{nxt}\n"
                )

# ---------- 필터 빌더 ----------

def norm_hex(c, default=None):
    """'#RRGGBB' / '0xRRGGBB' / 'RRGGBB' -> 'RRGGBB'(대문자). 잘못되면 default."""
    s = str(c or "").strip().lstrip("#")
    if s.lower().startswith("0x"):
        s = s[2:]
    if len(s) != 6:
        return default
    try:
        int(s, 16)
    except ValueError:
        return default
    return s.upper()


# 배경 그라데이션 기본 팔레트 — 딥 네이비 -> 보랏빛 -> 어두운 청록 (은은한 오로라)
DEFAULT_BG_GRAD = ["0B0F26", "241B4D", "0D2C44"]


def derive_bg_grad(bg_color):
    """단색 bg_color 를 기준으로 어울리는 3색 그라데이션 팔레트를 만든다."""
    import colorsys
    s = norm_hex(bg_color)
    if not s:
        return DEFAULT_BG_GRAD
    r, g, b = (int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, sa = colorsys.rgb_to_hls(r, g, b)

    def hx(h2, l2, s2):
        rr, gg, bb = colorsys.hls_to_rgb(
            h2 % 1.0, min(0.9, max(0.03, l2)), min(1.0, max(0.25, s2)))
        return f"{int(rr*255):02X}{int(gg*255):02X}{int(bb*255):02X}"

    return [hx(h, l, sa), hx(h + 0.09, l + 0.10, sa + 0.25),
            hx(h - 0.07, l + 0.05, sa + 0.20)]


def _kb_dir(seed):
    """seed(이미지 경로 등) 기반 결정적 방향(-1/+1). 매 렌더 같은 이미지는 같은 방향으로 팬."""
    h = int(hashlib.md5(str(seed).encode()).hexdigest(), 16)
    return 1 if h % 2 == 0 else -1


def kenburns_zoompan(frames, seed, zmax=1.4):
    """켄 번스 줌+팬 표현식 (z, x, y).

    zoompan 의 'zoom+델타' 방식은 프레임 수와 무관하게 고정 속도로 커지다가
    캡(zmax)에 도달하면 멈춰버려서, 곡이 길면 후반부 내내 정지 화면이 된다.
    대신 on(출력 프레임 번호)/frames 진행률에 smoothstep 이징을 걸어
    영상 길이 전체에 걸쳐 자연스럽게 감속하는 줌을 만들고,
    줌이 만든 여백(margin)만큼만 팬 하여 항상 프레임 안에 머물게 한다."""
    p = f"min(on/{max(1, frames)},1)"
    ease = f"(3*pow({p},2)-2*pow({p},3))"
    z = f"1+{zmax - 1:.4f}*{ease}"
    dirx, diry = _kb_dir(seed), _kb_dir(str(seed) + "y")
    x = f"iw/2-(iw/zoom/2)+{dirx}*0.5*(iw/2-(iw/zoom/2))"
    y = f"ih/2-(ih/zoom/2)+{diry}*0.3*(ih/2-(ih/zoom/2))"
    return z, x, y


def build_bg(bg_list, lay, duration, kenburns, bg_color, video_bg=None,
             bg_style="gradient", bg_grad=None):
    """
    배경 비디오 체인 빌드.
    반환: (extra_inputs, filter_parts, bg_label, audio_idx)
      extra_inputs: 배경 입력 -i 인자 리스트(앞쪽). audio_idx = 배경 입력 개수.
    우선순위: video_bg(영상) > bg_list(이미지) > 그라데이션/단색.
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
        if bg_style == "solid":
            return [], [f"color=c={bg_color}:s={W}x{H}:r={FPS}[bg]"], "[bg]", 0
        # 은은하게 흐르는 그라데이션 배경 (단색보다 훨씬 덜 밋밋함)
        cols = [norm_hex(c) for c in (bg_grad or [])]
        cols = [c for c in cols if c] or derive_bg_grad(bg_color)
        cparams = ":".join(f"c{i}=0x{c}" for i, c in enumerate(cols))
        return [], [
            f"gradients=s={W}x{H}:{cparams}:nb_colors={len(cols)}:"
            f"speed=0.008:r={FPS},format=yuv420p[bg]"
        ], "[bg]", 0

    inputs = []
    parts = []
    n = len(bg_list)

    if n == 1:
        inputs += ["-loop", "1", "-i", os.path.abspath(bg_list[0])]
        if kenburns:
            frames = max(1, round(duration * FPS))
            z, x, y = kenburns_zoompan(frames, bg_list[0])
            parts.append(
                f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                f"crop={W*2}:{H*2},"
                f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
                f"setsar=1[bg]"
            )
        else:
            parts.append(
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1,fps={FPS}[bg]"
            )
        return inputs, parts, "[bg]", 1

    # 다중 이미지: 각 L초씩 zoompan 후 xfade 크로스페이드
    fade = 1.0
    L = (duration + (n - 1) * fade) / n  # 각 클립 길이
    seg_frames = max(1, round(L * FPS))
    for i, img in enumerate(bg_list):
        inputs += ["-loop", "1", "-t", f"{L:.3f}", "-i", os.path.abspath(img)]
        if kenburns:
            z, x, y = kenburns_zoompan(seg_frames, img)
            parts.append(
                f"[{i}:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                f"crop={W*2}:{H*2},"
                f"zoompan=z='{z}':x='{x}':y='{y}':d={seg_frames}:s={W}x{H}:fps={FPS},"
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

# 비주얼라이저 기본 그라데이션 — 파스텔 스카이 -> 연보라 핑크 (드리미한 느낌)
DEFAULT_VIZ_COLORS = ["7DD3FC", "F0ABFC"]


def _viz_gradient_glow(raw_label, parts, W, h, colors, segmented=False):
    """흰색 비주얼라이저(2배 슈퍼샘플)를 알파 마스크로 써서 그라데이션을 입히고,
    겉광(넓고 은은) + 속광(좁고 밝음) + 선명한 본체 3레이어를 만든다.
    - 2x 렌더 후 lanczos 다운스케일: 계단 현상 없는 부드러운 곡선
    - segmented: 세로 갭을 넣어 막대를 또렷한 바 단위로 분할 (EQ 스타일)
    """
    c = [norm_hex(x) for x in (colors or [])]
    c = [x for x in c if x] or list(DEFAULT_VIZ_COLORS)
    if len(c) == 1:
        c = c * 2
    parts.append(f"{raw_label}scale={W}:{h}:flags=lanczos,"
                 f"format=rgba,alphaextract[vmask0]")
    mask = "[vmask0]"
    if segmented:
        # 주기적인 세로 검은 줄로 막대 사이 갭 생성
        seg = max(10, W // 96)          # 막대+갭 주기
        gap = max(3, seg * 2 // 5)      # 갭 두께
        parts.append(f"{mask}drawgrid=w={seg}:h={h * 4}:t={gap}:c=black[vmask]")
        mask = "[vmask]"
    parts.append(
        f"gradients=s={W}x{h}:c0=0x{c[0]}:c1=0x{c[1]}:"
        f"x0=0:y0={h // 2}:x1={W}:y1={h // 2}:speed=0.006:r={FPS}[vgrad]")
    parts.append(f"[vgrad]{mask}alphamerge[vcol]")
    parts.append("[vcol]split=3[vsharp][vs1][vs2]")
    parts.append("[vs1]gblur=sigma=5[vglow1]")                       # 속광
    parts.append("[vs2]gblur=sigma=18,colorchannelmixer=aa=0.65[vglow2]")  # 겉광
    return ["[vglow2]", "[vglow1]", "[vsharp]"]


def build_viz(audio_spec, lay, viz, colors=None):
    """비주얼라이저 체인. 반환: (parts, overlay_labels) — 라벨 순서대로 배경 위에 겹친다."""
    W = lay["W"]
    h = lay["viz_h"]
    parts = []
    if viz == "none":
        return [], []
    if viz == "waves":
        # 부드러운 중앙 대칭 파형 + 그라데이션 + 이중 글로우 (기본)
        parts.append(f"[{audio_spec}]showwaves=s={W * 2}x{h * 2}:mode=cline:"
                     f"colors=white:rate={FPS}[vraw]")
        labels = _viz_gradient_glow("[vraw]", parts, W, h, colors)
        return parts, labels
    if viz == "bars":
        # 갭이 있는 또렷한 EQ 막대 + 그라데이션 + 이중 글로우
        parts.append(f"[{audio_spec}]showfreqs=s={W * 2}x{h * 2}:mode=bar:ascale=log:"
                     f"fscale=log:win_size=2048:colors=white:rate={FPS}[vraw]")
        labels = _viz_gradient_glow("[vraw]", parts, W, h, colors, segmented=True)
        return parts, labels
    if viz == "line":
        # 미니멀: 얇은 그라데이션 라인 + 은은한 글로우 (잔잔한 곡용)
        lh = max(2, (h * 3 // 5) - ((h * 3 // 5) % 2))
        c = [norm_hex(x) for x in (colors or [])]
        c = [x for x in c if x] or list(DEFAULT_VIZ_COLORS)
        if len(c) == 1:
            c = c * 2
        parts.append(f"[{audio_spec}]showwaves=s={W * 2}x{lh * 2}:mode=p2p:"
                     f"colors=white:rate={FPS}[lraw]")
        parts.append(f"[lraw]scale={W}:{lh}:flags=lanczos,"
                     f"format=rgba,alphaextract[lmask]")
        parts.append(
            f"gradients=s={W}x{lh}:c0=0x{c[0]}:c1=0x{c[1]}:"
            f"x0=0:y0={lh // 2}:x1={W}:y1={lh // 2}:speed=0.006:r={FPS}[lgrad]")
        parts.append("[lgrad][lmask]alphamerge,colorchannelmixer=aa=0.9[lcol]")
        parts.append("[lcol]split[lsharp][lsoft]")
        parts.append("[lsoft]gblur=sigma=4,colorchannelmixer=aa=0.5[lglow]")
        return parts, ["[lglow]", "[lsharp]"]
    if viz == "cqt":
        return [f"[{audio_spec}]showcqt=s={W}x{h}:count=2:gamma=4,"
                "format=yuva420p[viz]"], ["[viz]"]
    if viz == "spectrum":
        return [f"[{audio_spec}]showspectrum=s={W}x{h}:mode=combined:"
                "color=intensity:scale=cbrt:slide=scroll,format=yuva420p[viz]"], ["[viz]"]
    return [], []

# ---------- 텍스트 파일(drawtext용) ----------

def write_textfile(text, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

# ---------- 레코드 모드 (회전 원형 앨범아트) ----------

_ROTATE_EVAL_SUPPORTED = None


def rotate_eval_flag():
    """rotate 필터의 'eval' 옵션 지원 여부(캐시).

    구버전 ffmpeg 는 eval 옵션이 있고 기본값이 'init' 이라 각도 표현식(t 포함)이
    최초 1회만 평가되어 회전이 아예 멈춰 보인다 — eval=frame 필요.
    신버전(옵션 자체가 사라짐, 예: 8.x)은 항상 프레임마다 재평가하므로
    eval=frame 을 붙이면 "Option not found" 로 렌더가 실패한다."""
    global _ROTATE_EVAL_SUPPORTED
    if _ROTATE_EVAL_SUPPORTED is None:
        try:
            out = subprocess.run(["ffmpeg", "-h", "filter=rotate"],
                                  capture_output=True, text=True, timeout=5).stdout
        except Exception:
            out = ""
        _ROTATE_EVAL_SUPPORTED = bool(re.search(r"^\s*eval\s", out, re.MULTILINE))
    return _ROTATE_EVAL_SUPPORTED


def disc_diameter(lay):
    """레코드(원형 앨범아트) 지름. 가로형은 화면 높이, 세로형은 폭 기준."""
    W, H = lay["W"], lay["H"]
    d = int(W * 0.55) if H > W else int(H * 0.42)
    return d - (d % 2)


def make_disc_png(src, out_path, size):
    """앨범아트 -> 원형 마스킹 + 흰 테두리 링 PNG (프리패스, 1프레임).
    본 렌더에선 이 PNG 를 rotate 로 돌리기만 하면 되어 프레임당 비용이 적다."""
    D = size - (size % 2)
    c = (D - 1) / 2
    R = D / 2 - 2          # 소프트 엣지 여유
    ring_w = max(4, D // 52)
    ring = f"between(hypot(X-{c:.1f},Y-{c:.1f}),{R - ring_w:.1f},{R:.1f})"
    a_expr = f"255*clip(({R:.1f}-hypot(X-{c:.1f},Y-{c:.1f}))/2+1,0,1)"
    vf = (
        f"scale={D}:{D}:force_original_aspect_ratio=increase,crop={D}:{D},"
        f"format=gbrap,"
        f"geq=r='if({ring},248,r(X,Y))':g='if({ring},248,g(X,Y))':"
        f"b='if({ring},248,b(X,Y))':a='{a_expr}'"
    )
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", os.path.abspath(src),
           "-vf", vf, "-frames:v", "1", os.path.abspath(out_path)]
    if run(cmd).returncode != 0:
        sys.exit("레코드 모드: 앨범아트 원형 마스킹 실패")

# ---------- 반짝이는 음표 파티클 (배경 장식) ----------

SPARKLE_COUNT = 6


def sparkle_params(i):
    """파티클 i 번째의 결정적 위치/속도/위상 (매 렌더 동일하게 재현, 씨앗=인덱스)."""
    h = int(hashlib.md5(f"sparkle{i}".encode()).hexdigest(), 16)
    base_x = h % 997
    base_y = (h // 997) % 997
    speed_x = 6 + (h % 11)            # 6~16 px/s, 옆으로 은은하게 표류
    speed_y = 9 + (h % 13)             # 9~21 px/s, 위로 떠오름
    phase = (h % 6283) / 1000.0        # 0~2PI 근사
    period = 2.6 + (h % 9) * 0.3       # 2.6~5.3s 반짝임 주기
    size = 20 + (h % 3) * 8             # 20/28/36
    return base_x, base_y, speed_x, speed_y, phase, period, size


def build_sparkle(cur, W, H):
    """cur 레이블 위에 은은히 떠다니는 ♪ 파티클 N개를 순서대로 합성.
    화면 크기(W+60/H+60)를 mod 로 감싸 좌우/상하 경계 없이 무한 순환한다."""
    parts = []
    for i in range(SPARKLE_COUNT):
        bx, by, sx, sy, phase, period, size = sparkle_params(i)
        x_expr = f"mod({bx}+{sx}*t,{W}+60)-30"
        y_expr = f"{H}+30-mod({by}+{sy}*t,{H}+60)"
        a_expr = f"0.10+0.16*(0.5+0.5*sin(2*PI*t/{period:.3f}+{phase:.3f}))"
        parts.append(
            f"{cur}drawtext={symbol_font_spec()}:text='♪':fontcolor=white@0.9:"
            f"fontsize={size}:x='{x_expr}':y='{y_expr}':alpha='{a_expr}'[vspk{i}]")
        cur = f"[vspk{i}]"
    return parts, cur

# ---------- 렌더 ----------

def render(audio, ass_path, out, lay, bg_list=None, viz="waves",
           bg_color="0x0a0a14", duration=None, kenburns=True,
           clip_start=None, clip_len=None, watermark=None, logo=None,
           video_bg=None, crf=18, scale=1.0, preset="slow",
           normalize=False, master=False, fade_in=0.0, fade_out=0.0,
           vignette=False, grain=False, bg_pulse=False,
           intro_card=False, ic_title="", ic_artist="", gaps=None,
           viz_colors=None, bg_style="gradient", bg_grad=None,
           scrim=False, disc_png=None, progress_bar=False,
           sparkle=False, outro_cta=False, outro_cta_text=""):
    work_dir = os.path.dirname(os.path.abspath(ass_path)) or "."
    ass_name = os.path.basename(ass_path)
    W, H = lay["W"], lay["H"]

    extra_inputs, bg_parts, bg_label, audio_idx = build_bg(
        bg_list, lay, duration, kenburns, bg_color, video_bg=video_bg,
        bg_style=bg_style, bg_grad=bg_grad)
    audio_spec = f"{audio_idx}:a"

    parts = list(bg_parts)

    # ---- 오디오 반응 배경(밝기 펄스): RMS 엔벨로프 -> sendcmd -> eq ----
    if bg_pulse:
        env = audio_rms_envelope(audio)
        if env:
            vals = sorted(d for _, d in env)
            base = vals[len(vals) // 2]  # 중앙값
            off = clip_start or 0.0
            lines = []
            for t, d in env:
                ot = t - off
                if ot < 0 or (duration and ot > duration):
                    continue
                b = max(-0.07, min(0.15, (d - base) * 0.02))
                lines.append(f"{ot:.2f} eq brightness {b:.3f};")
            if lines:
                write_textfile("\n".join(lines), os.path.join(work_dir, "_pulse.cmd"))
                parts.append(f"{bg_label}sendcmd=f=_pulse.cmd,"
                             f"eq=brightness=0:eval=frame[bgp]")
                bg_label = "[bgp]"

    # ---- 오디오 필터 체인 (loudnorm / 페이드) ----
    # 유튜브 기준 -14 LUFS 정규화 + 인트로/아웃트로 페이드.
    afilters = []
    if master:
        # 2-pass loudnorm(정밀 -14 LUFS) + 리미터(클리핑 방지)
        afilters.append(loudnorm_filter(audio, two_pass=True))
        afilters.append("alimiter=limit=0.97")
    elif normalize:
        afilters.append(loudnorm_filter(audio, two_pass=False))
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

    # ---- 하단 스크림: 밝은 배경에서 파형/자막 가독성 확보 ----
    if scrim:
        sh = int(H * 0.38)
        sh -= sh % 2
        parts.append(f"color=c=black:s={W}x{sh}:r={FPS},format=yuva420p[scb]")
        # 위(투명)→아래(약 55% 어둡게) 세로 그라데이션을 알파로 사용
        parts.append(
            f"gradients=s={W}x{sh}:c0=0x000000:c1=0x8C8C8C:"
            f"x0=0:y0=0:x1=0:y1={sh}:speed=0.00001:r={FPS},format=gray[scm]")
        parts.append("[scb][scm]alphamerge[scrim]")
        parts.append(f"{bg_label}[scrim]overlay=0:{H - sh}:format=auto[bgsc]")
        bg_label = "[bgsc]"

    viz_parts, viz_labels = build_viz(viz_audio, lay, viz, colors=viz_colors)
    parts += list(viz_parts)

    cur = bg_label
    for i, lbl in enumerate(viz_labels):
        parts.append(f"{cur}{lbl}overlay=0:{lay['viz_y']}:format=auto[vmix{i}]")
        cur = f"[vmix{i}]"

    # ---- 반짝이는 음표 파티클: 은은하게 떠다니는 ♪ (배경 장식) ----
    if sparkle:
        spk_parts, cur = build_sparkle(cur, W, H)
        parts += spk_parts

    # ---- 레코드 모드: 원형 앨범아트가 천천히 회전 ----
    disc_idx = None
    if disc_png:
        D = disc_diameter(lay)
        disc_idx = audio_idx + 1 + (1 if logo else 0)
        cy = int(H * 0.30) if H > W else int(H * 0.36)  # 세로형은 조금 위
        rotate_expr = f"rotate=2*PI*t/16:ow={D}:oh={D}:c=black@0"
        if rotate_eval_flag():
            rotate_expr += ":eval=frame"
        parts.append(
            f"[{disc_idx}:v]format=rgba,{rotate_expr},fps={FPS}[disc]")
        parts.append(f"{cur}[disc]overlay={(W - D) // 2}:{cy - D // 2}[vdisc]")
        cur = "[vdisc]"

    # 자막 burn-in (동봉 fonts/ 를 fontsdir 로 등록)
    parts.append(f"{cur}{subtitles_filter(ass_name)}[vsub]")
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
            f"{cur}drawtext={draw_font_spec()}:textfile={wm_file}:"
            f"fontcolor=white@0.55:fontsize={wm_fs}:x=w-tw-{pad}:y=h-th-{int(round(30*scale))}:"
            "shadowcolor=black@0.6:shadowx=2:shadowy=2[vout]"
        )
        cur = "[vout]"

    # ---- 인트로 타이틀 카드 (시작 ~4초 페이드인) ----
    if intro_card and ic_title:
        a_expr = ("alpha='if(lt(t,0.6),t/0.6,if(lt(t,3.2),1,"
                  "if(lt(t,4),(4-t)/0.8,0)))'")
        write_textfile(ic_title, os.path.join(work_dir, "_ic_ttl.txt"))
        parts.append(
            f"{cur}drawtext={draw_font_spec()}:textfile=_ic_ttl.txt:fontcolor=white:"
            f"fontsize={int(round(96*scale))}:x=(w-tw)/2:y=(h-th)/2-{int(round(20*scale))}:"
            f"{a_expr}:shadowcolor=black@0.7:shadowx=3:shadowy=3[vic]")
        cur = "[vic]"
        if ic_artist:
            write_textfile(ic_artist, os.path.join(work_dir, "_ic_art.txt"))
            parts.append(
                f"{cur}drawtext={draw_font_spec()}:textfile=_ic_art.txt:fontcolor=white@0.9:"
                f"fontsize={int(round(46*scale))}:x=(w-tw)/2:y=(h-th)/2+{int(round(72*scale))}:"
                f"{a_expr}:shadowcolor=black@0.7:shadowx=2:shadowy=2[vica]")
            cur = "[vica]"

    # ---- 간주(가사 없는 긴 구간)에 ♪ 표시 ----
    if gaps:
        enable = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e in gaps)
        parts.append(
            f"{cur}drawtext={symbol_font_spec()}:text='♪':fontcolor=white@0.45:"
            f"fontsize={int(round(120*scale))}:x=(w-tw)/2:y=(h-th)/2:"
            f"enable='{enable}'[vnote]")
        cur = "[vnote]"

    # ---- 곡 진행바: 하단 얇은 라인 (파형 색과 통일) ----
    if progress_bar and duration:
        ph = max(4, int(round(6 * scale)))
        accent = norm_hex((viz_colors or [None])[0], DEFAULT_VIZ_COLORS[0])
        parts.append(f"color=c=0x{accent}@0.85:s={W}x{ph}:r={FPS}[pbar]")
        parts.append(
            f"{cur}[pbar]overlay=x='-w+w*t/{duration:.3f}':y={H - ph}[vpb]")
        cur = "[vpb]"

    # ---- 아웃트로 구독 유도 카드: 곡 끝 ~4초에 페이드인 ----
    if outro_cta and duration:
        cta_dur = min(4.0, duration)
        start = max(0.0, duration - cta_dur)
        text = outro_cta_text or "구독과 좋아요 부탁드려요"
        write_textfile(text, os.path.join(work_dir, "_outro_cta.txt"))
        a_expr = (f"alpha='if(lt(t,{start:.3f}),0,"
                  f"if(lt(t,{start + 0.6:.3f}),(t-{start:.3f})/0.6,1))'")
        parts.append(
            f"{cur}drawtext={draw_font_spec()}:textfile=_outro_cta.txt:"
            f"fontcolor=white:fontsize={int(round(52 * scale))}:"
            f"x=(w-tw)/2:y=(h-th)/2:{a_expr}:"
            "shadowcolor=black@0.7:shadowx=2:shadowy=2[vcta]")
        cur = "[vcta]"

    # ---- 영상 피니셔 (분위기) : 비네트 -> 필름그레인 -> 페이드 ----
    if vignette:
        parts.append(f"{cur}vignette=PI/4[vvig]")
        cur = "[vvig]"
    if grain:
        # 루마 채널만 노이즈 -> 컬러 반점 없는 진짜 필름 그레인 느낌
        parts.append(f"{cur}noise=c0s=10:c0f=t+u[vgrain]")
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
    # lanczos: 배경 확대/크롭 시 기본(bicubic)보다 또렷한 리샘플링
    cmd = ["ffmpeg", "-y", "-sws_flags", "lanczos+accurate_rnd+full_chroma_int"]
    cmd += extra_inputs
    if clip_start is not None:
        cmd += ["-ss", f"{clip_start:.3f}"]
    cmd += ["-i", os.path.abspath(audio)]
    if logo:
        cmd += ["-i", os.path.abspath(logo)]
    if disc_png:
        cmd += ["-loop", "1", "-i", os.path.abspath(disc_png)]

    cmd += [
        "-filter_complex", full_filter,
        "-map", final_v,
        "-map", audio_map,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
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

def make_thumbnail(out_path, title, artist=None, bg=None, bg_color="0x0a0a14",
                   accent=None):
    work_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    W, Ht = 1280, 720
    write_textfile(title, os.path.join(work_dir, "_ttl.txt"))
    accent = norm_hex(accent, DEFAULT_VIZ_COLORS[0])
    vf = []
    if bg:
        src = ["-i", os.path.abspath(bg)]
        vf.append(f"scale={W}:{Ht}:force_original_aspect_ratio=increase,crop={W}:{Ht}")
    else:
        # 배경 이미지가 없으면 영상과 같은 그라데이션 톤 (단색보다 예쁘다)
        cols = derive_bg_grad(bg_color)
        cparams = ":".join(f"c{i}=0x{c}" for i, c in enumerate(cols))
        src = ["-f", "lavfi", "-i",
               f"gradients=s={W}x{Ht}:{cparams}:nb_colors={len(cols)}"]
    vf.append(f"drawbox=0:0:{W}:{Ht}:color=black@0.35:t=fill")
    vf.append(
        f"drawtext={draw_font_spec()}:textfile=_ttl.txt:fontcolor=white:"
        "fontsize=96:x=(w-tw)/2:y=(h-th)/2-52:"
        "shadowcolor=black@0.8:shadowx=3:shadowy=3"
    )
    # 제목 아래 포인트 컬러 바 — 비주얼라이저 색과 톤을 맞춘다
    vf.append(f"drawbox=x=(iw-300)/2:y={Ht // 2 + 28}:w=300:h=10:"
              f"color=0x{accent}@0.95:t=fill")
    if artist:
        write_textfile(artist, os.path.join(work_dir, "_art.txt"))
        vf.append(
            f"drawtext={draw_font_spec()}:textfile=_art.txt:fontcolor=white@0.85:"
            f"fontsize=48:x=(w-tw)/2:y={Ht // 2 + 78}:"
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
                    choices=["waves", "bars", "line", "cqt", "spectrum", "none"])
    ap.add_argument("--viz-color", nargs="+", metavar="RRGGBB",
                    help="비주얼라이저 그라데이션 색 1~2개 (기본 파스텔 하늘→핑크)")
    ap.add_argument("--bg-color", default="0x0a0a14")
    ap.add_argument("--bg-style", choices=["gradient", "solid"], default="gradient",
                    help="배경 이미지가 없을 때: gradient=흐르는 그라데이션(기본), solid=단색")
    ap.add_argument("--bg-grad", nargs="+", metavar="RRGGBB",
                    help="그라데이션 배경 색 목록 (기본: bg-color 에서 자동 유도)")
    ap.add_argument("--kenburns", action=argparse.BooleanOptionalAction,
                    default=True, help="배경 줌/팬 (기본 on, --no-kenburns 로 끔)")
    ap.add_argument("--scrim", action=argparse.BooleanOptionalAction, default=None,
                    help="하단 가독성 스크림. 기본: 배경 이미지/영상이 있으면 자동 on")
    ap.add_argument("--disc", action="store_true",
                    help="레코드 모드: 원형 앨범아트가 중앙에서 천천히 회전")
    ap.add_argument("--disc-art", help="레코드 모드 앨범아트 (기본: 첫 --bg 이미지)")
    ap.add_argument("--progress-bar", action="store_true",
                    help="하단 곡 진행바 (파형 색과 통일)")
    # 가사 싱크
    ap.add_argument("--align", choices=["none", "auto"], default="none",
                    help="auto: stable-ts 로 가사 강제정렬")
    ap.add_argument("--align-model", default="base", help="정렬 모델 (tiny/base/small/medium)")
    ap.add_argument("--align-lang", default="ko", help="정렬 언어 코드 (기본 ko)")
    ap.add_argument("--intro", type=float, default=0.0, help="txt 균등분배: 첫 가사 전(초)")
    ap.add_argument("--outro", type=float, default=0.0, help="txt 균등분배: 끝 여백(초)")
    ap.add_argument("--lrc-out", help="초안 LRC 만 생성하고 종료")
    ap.add_argument("--font", default=SUB_FONT, help="자막 폰트(한글 지원)")
    ap.add_argument("--sub-color", default="FFFFFF", help="자막 색 (RRGGBB, 기본 흰색)")
    ap.add_argument("--sub-size", type=float, default=1.0, help="자막 크기 배율 (기본 1.0)")
    ap.add_argument("--sub-pos", choices=["bottom", "middle", "top"], default="bottom",
                    help="자막 세로 위치")
    ap.add_argument("--sub-glow", action="store_true", help="자막 발광(blur) 효과")
    ap.add_argument("--sub-fade", action=argparse.BooleanOptionalAction, default=True,
                    help="소절 단위 페이드 인/아웃 (기본 on, --no-sub-fade 로 끔)")
    ap.add_argument("--sub-preview", action=argparse.BooleanOptionalAction, default=False,
                    help="다음 소절 미리보기 (현재 줄 아래 작고 흐리게)")
    ap.add_argument("--intro-card", action="store_true",
                    help="시작 ~4초 제목/아티스트 페이드인 오프닝")
    ap.add_argument("--interlude-note", action="store_true",
                    help="가사 없는 긴 구간(간주)에 ♪ 표시")
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
                    help="유튜브 기준 -14 LUFS 라우드니스 정규화(1-pass)")
    ap.add_argument("--master", action="store_true",
                    help="정밀 마스터링: 2-pass loudnorm + 리미터(클리핑 방지)")
    ap.add_argument("--karaoke", action="store_true",
                    help="가사 카라오케 색채움(줄 지속시간을 글자에 분배)")
    ap.add_argument("--fade-in", type=float, default=0.0, help="인트로 페이드(초, 영상+오디오)")
    ap.add_argument("--fade-out", type=float, default=0.0, help="아웃트로 페이드(초, 영상+오디오)")
    ap.add_argument("--vignette", action="store_true", help="비네트(가장자리 어둡게)")
    ap.add_argument("--film-grain", action="store_true", help="필름 그레인(노이즈) 질감")
    ap.add_argument("--bg-pulse", action="store_true",
                    help="오디오 음량에 반응해 배경 밝기가 미세하게 펄스")
    ap.add_argument("--sparkle", action="store_true",
                    help="은은하게 떠다니는 ♪ 파티클 (배경 장식)")
    ap.add_argument("--outro-cta", action="store_true",
                    help="곡 끝 ~4초에 구독/좋아요 유도 카드 페이드인")
    ap.add_argument("--outro-cta-text", default="",
                    help="아웃트로 카드 문구 (기본: '구독과 좋아요 부탁드려요')")
    ap.add_argument("--preview-secs", type=int, default=0,
                    help=">0 이면 앞 N초만 저화질·초고속으로 렌더(미리보기)")
    args = ap.parse_args()

    global FPS
    FPS = args.fps
    scale = {"1080": 1.0, "1440": 4 / 3, "2160": 2.0}[args.res]
    crf = 18
    preset = "slow"
    if args.preview_secs > 0:
        # 미리보기: 720p 상당 + 초고속 인코딩 + crf 높임
        scale = min(scale, 720 / 1080)
        preset = "ultrafast"
        crf = 30

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
    if args.preview_secs > 0:
        render_dur = min(render_dur, float(args.preview_secs))

    # 가사 -> cues (전체 곡 기준)
    cues = []
    if args.lyrics:
        ext = os.path.splitext(args.lyrics)[1].lower()
        if args.align == "auto":
            lines = read_txt_lines(args.lyrics) if ext != ".lrc" else \
                [t for _, t in parse_lrc(args.lyrics)]
            cues = align_with_stable_ts(args.audio, "\n".join(lines), args.align_model,
                                        language=args.align_lang)
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
              size_mult=args.sub_size, pos=args.sub_pos, karaoke=args.karaoke,
              glow=args.sub_glow, fade=args.sub_fade, preview=args.sub_preview)

    # 스크림: 명시 지정 없으면 배경 이미지/영상이 있을 때 자동 on
    scrim = args.scrim if args.scrim is not None else bool(args.bg or args.video_bg)

    # 레코드 모드: 앨범아트 원형 마스킹 프리패스
    disc_png = None
    if args.disc:
        art = args.disc_art or (args.bg[0] if args.bg else None)
        if art and os.path.exists(art):
            disc_png = os.path.join(out_dir, "_disc.png")
            make_disc_png(art, disc_png, disc_diameter(lay))
        else:
            print("[warn] --disc 에 쓸 앨범아트가 없습니다 "
                  "(--disc-art 또는 --bg 필요) — 레코드 모드 생략")

    # 간주(가사 없는 긴 구간) 검출 -> ♪ 표시용 구간
    gaps = []
    if args.interlude_note and cues:
        GAP = 4.0
        if cues[0][0] >= GAP:
            # 인트로 카드가 있으면 카드(~4초) 이후부터 ♪
            lead = 4.5 if args.intro_card else 0.5
            if cues[0][0] - 0.3 - lead >= 1.0:
                gaps.append((lead, cues[0][0] - 0.3))
        for i in range(len(cues) - 1):
            s, e = cues[i][1], cues[i + 1][0]
            if e - s >= GAP:
                gaps.append((s + 0.3, e - 0.3))
        if render_dur - cues[-1][1] >= GAP:
            gaps.append((cues[-1][1] + 0.3, render_dur - 0.3))

    render(args.audio, ass_path, args.out, lay,
           bg_list=args.bg, viz=args.viz, bg_color=args.bg_color,
           duration=render_dur, kenburns=args.kenburns,
           clip_start=clip_start, clip_len=clip_len,
           watermark=args.watermark, logo=args.logo,
           video_bg=args.video_bg, scale=scale, preset=preset, crf=crf,
           normalize=args.normalize, master=args.master,
           fade_in=args.fade_in, fade_out=args.fade_out,
           vignette=args.vignette, grain=args.film_grain, bg_pulse=args.bg_pulse,
           intro_card=args.intro_card, ic_title=args.title or "",
           ic_artist=args.artist or "", gaps=gaps,
           viz_colors=args.viz_color, bg_style=args.bg_style, bg_grad=args.bg_grad,
           scrim=scrim, disc_png=disc_png, progress_bar=args.progress_bar,
           sparkle=args.sparkle, outro_cta=args.outro_cta,
           outro_cta_text=args.outro_cta_text)

    # 썸네일 (미리보기에선 생략)
    if args.title and args.preview_secs == 0:
        thumb = args.thumb_out or (os.path.splitext(args.out)[0] + "_thumb.jpg")
        bg0 = args.bg[0] if args.bg else None
        accent = (args.viz_color or DEFAULT_VIZ_COLORS)[0]
        make_thumbnail(thumb, args.title, args.artist, bg=bg0,
                       bg_color=args.bg_color, accent=accent)

    if not args.keep_ass:
        for tmp in ("_sub.ass", "_wm.txt", "_ttl.txt", "_art.txt",
                    "_ic_ttl.txt", "_ic_art.txt", "_pulse.cmd", "_disc.png",
                    "_outro_cta.txt"):
            try:
                os.remove(os.path.join(out_dir, tmp))
            except OSError:
                pass

if __name__ == "__main__":
    main()
