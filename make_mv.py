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
import math
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

_SECTION_TAG_RE = re.compile(r"^(?:\s*\[[^\[\]]*\])+\s*$")
_STAGE_DIRECTION_RE = re.compile(r"^(?:\s*\([^()]*\))+\s*$")

def is_section_tag_line(line):
    """줄 전체가 대괄호 태그([Verse 1], [Chorus] 등)로만 이루어졌는지. 항상 비가사."""
    return bool(_SECTION_TAG_RE.match(line.strip()))

def is_stage_direction_line(line):
    """줄 전체가 괄호 지시문((Chanting, bouncy) 등)으로만 이루어졌는지. 실제로 불릴
    수도 있어 판단이 애매 — 호출부에서 오디오 인식 여부에 따라 다르게 취급한다."""
    return bool(_STAGE_DIRECTION_RE.match(line.strip()))

def filter_lyric_lines(lines, drop_stage_directions=True):
    """SUNO 프롬프트 형식 줄(섹션 태그/연출 지시문)을 싱크 타이밍 계산에서 제외한다.
    실제 가사 줄에 붙은 인라인 애드립(예: '...밑선 (Hey!)')은 줄 전체가 괄호가
    아니므로 걸리지 않고 그대로 유지된다. 원본 가사 텍스트/파일 자체는 건드리지 않고
    타이밍 계산용 줄 목록만 정리한다. 반환: (남은 줄, 제외된 줄)."""
    kept, dropped = [], []
    for ln in lines:
        s = ln.strip()
        if is_section_tag_line(s) or (drop_stage_directions and is_stage_direction_line(s)):
            dropped.append(ln)
        else:
            kept.append(ln)
    return kept, dropped

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
             bg_style="gradient", bg_grad=None, disc_bg_style="off"):
    """
    배경 비디오 체인 빌드.
    반환: (extra_inputs, filter_parts, bg_label, audio_idx)
      extra_inputs: 배경 입력 -i 인자 리스트(앞쪽). audio_idx = 배경 입력 개수.
    우선순위: video_bg(영상) > bg_list(이미지) > 그라데이션/단색.

    disc_bg_style="glow" 면 이미지 배경(단일/다중 공통)을 블러+채도업 처리해 레코드
    모드 배경을 앨범아트 색감으로 가득 채운다(스포티파이 '재생 중' 화면 느낌). 밝기는
    일부러 건드리지 않음 — 이미 어두운 앨범아트를 더 죽이면 오히려 칙칙해지고, 자막
    가독성은 별도의 scrim(하단 그라데이션)이 이미 담당하므로 중복 어둡힘이 불필요.
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

    glow = disc_bg_style == "glow"

    if n == 1:
        inputs += ["-loop", "1", "-i", os.path.abspath(bg_list[0])]
        lbl = "[bgraw]" if glow else "[bg]"
        if kenburns:
            frames = max(1, round(duration * FPS))
            z, x, y = kenburns_zoompan(frames, bg_list[0])
            parts.append(
                f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                f"crop={W*2}:{H*2},"
                f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
                f"setsar=1{lbl}"
            )
        else:
            parts.append(
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1,fps={FPS}{lbl}"
            )
        if glow:
            parts.append(
                "[bgraw]gblur=sigma=42:steps=2,eq=saturation=1.4[bg]")
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
        out_lbl = ("bgraw" if glow else "bg") if i == n - 1 else f"x{i}"
        parts.append(
            f"[{prev}][b{i}]xfade=transition=fade:duration={fade}:"
            f"offset={offset:.3f}[{out_lbl}]"
        )
        prev = out_lbl
    if glow:
        parts.append(
            "[bgraw]gblur=sigma=42:steps=2,"
            "eq=brightness=-0.10:saturation=1.35[bg]")
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


# lp_vinyl/text_ring 테마 치수·오프셋. PNG 프리패스 생성(main)과 filter_complex
# 오버레이 배치(render) 양쪽에서 같은 값을 참조해야 크기가 어긋나지 않는다.
# 디자인 레퍼런스(sample/palylist_sample2.png)를 원 피팅(circle fit)으로 실측하면
# 비닐이 커버보다 오히려 작고(지름 ≈0.90×D) 커버 중심에서 오른쪽으로 ≈0.51×D
# 떨어져 있다 — 초기에 눈대중으로 잡았던 1.3/0.40 은 컸다(LP_VINYL_SIZE_SCALE 적용
# 후 비닐이 화면 위로 잘려나가는 걸로 드러남). 실측치로 교체.
#
# 이후 실사용 리뷰(sample/playscreen.png, 실제 앨범아트로 렌더): palylist_sample2
# 는 일러스트 커버라 실측 그대로 적용하면(SIZE_SCALE=1.5, SCALE=0.90) 복잡한
# 실사진 커버에서는 커버/비닐 조합이 과하게 크고, 커버가 비닐보다 눈에 띄게
# 커 보였다(제품 오너 피드백: "앨범이미지 좀 줄여, LP판보다 진짜 살짝 더 큰
# 정도로"). 커버가 "살짝만" 더 크도록 LP_VINYL_SCALE 을 0.90 -> 0.96 으로,
# 조합 전체 크기를 LP_VINYL_SIZE_SCALE 1.5 -> 1.3 으로 낮춘다 — 실측치보다
# 제품 오너의 육안 피드백 + 실제 렌더 프레임 비교를 우선한다.
LP_VINYL_SCALE = 0.96      # 비닐 지름 = D_lp * 이 값 (커버보다 "살짝만" 작게)
LP_VINYL_OFFSET = 0.51     # 커버 중심 기준 (기본 오른쪽으로) 삐져나오는 양(D_lp 배수) —
                           # --disc-lp-side 로 방향은 바꿀 수 있지만 이 비율 자체는
                           # 레퍼런스 실측 근거가 있어 그대로 둔다(위 주석 참고).
# 실제 렌더 리뷰 후 제품 오너 피드백("비닐이 조금 더 삐져나와도 될 것 같아"): 비율
# (LP_VINYL_OFFSET)은 레퍼런스 실측 근거가 있어 그대로 두고, 그 위에 고정 픽셀만
# 살짝 더 얹는다 — 스케일에 비례해야 해상도가 달라져도 같은 느낌이 유지되므로
# round(이 값 * scale) 로 적용한다(off_x 계산부, render() lp_vinyl 분기 참고).
LP_VINYL_OFFSET_NUDGE_PX = 10
TEXT_RING_SCALE = 1.15     # 텍스트 링 지름 = D * 이 값 (커버에 가깝게 → 위아래 노출 최소화)
TEXT_RING_OFFSET = 0.30    # 커버 중심 기준 왼쪽으로 밀어 초승달 형태로 노출(D 배수)

# lp_vinyl 전용 커버 확대 배율(이력용 상수, 현재는 1.0=확대 없음). disc_diameter()
# 는 모든 디스크 테마가 공유하는 함수라(classic/text_ring/square_spin 이 그대로
# 의존) 여기서 바꾸면 안 되지만, 한때 디자인 레퍼런스(sample/palylist_sample2.png)
# 실측(커버 높이/프레임 높이 ≈0.64 vs disc_diameter() 의 ≈0.42)에 맞춰 lp_vinyl
# 커버만 disc_diameter() 결과(D)보다 30% 크게(1.3배) 키운 적이 있었다(1.5 ->
# 제품 오너 피드백으로 1.3 까지 낮춤).
#
# 이후 제품 오너 피드백: 테마를 바꿔가며 비교해보니 lp_vinyl 만 앨범 커버 자체가
# 다른 세 테마(classic/text_ring/square_spin)보다 눈에 띄게 커 보인다 — "앨범
# 크기"는 테마와 무관하게 일관돼야 하고(비닐이 뒤로 삐져나오는 건 별개의 장식
# 요소이지 커버 확대가 아니다), 그래서 1.0 으로 되돌려 커버 베이스라인을 D 로
# 통일한다. LP_VINYL_OFFSET/LP_VINYL_OFFSET_NUDGE_PX/LP_VINYL_SCALE 은 비닐이
# 커버 뒤로 삐져나오는 정도를 다루는 별개 상수라 이 변경과 무관, 그대로 둔다.
#
# 상수 자체(이름과 D_lp = int(D * LP_VINYL_SIZE_SCALE) 곱셈)는 그대로 남겨둔다 —
# main() 프리패스(PNG 생성)와 render() 오버레이 배치, disc_theme_max_extent() 세
# 곳 모두 이미 이 상수를 통해서만 D_lp 를 계산하므로(1.3 -> 1.0 변경 시 그대로
# 세 곳 모두 일관되게 반영됨), 곱셈 자체를 걷어내는 것보다 상수값만 1.0 으로
# 바꾸는 쪽이 "PNG 프리패스와 오버레이 배치가 어긋나면 안 된다"는 위험을 새로
# 만들지 않는 가장 작은 변경이다.
LP_VINYL_SIZE_SCALE = 1.0


# 진행바 폭 = 프레임 폭의 이 비율(가운데 정렬). 디자인 레퍼런스
# (sample/playlist_sample1.png)를 PIL 로 실측하면 bar_width/image_width ≈0.26 인
# 알약형 바가 화면 중앙에 떠 있는 구도다 — 예전 공식(margin_x=70px 고정)은 여백이
# 해상도와 무관한 절대 픽셀값이라 1080p 기준 bar_w/W ≈0.93(거의 풀폭)까지 벌어져
# 레퍼런스보다 훨씬 넓었다. margin_x 를 W 에 비례시켜야 어떤 해상도/scale 에서도
# 비율이 유지된다.
PROGRESS_BAR_WIDTH_FRAC = 0.27


def progress_bar_geometry(W, H, scale=1.0, pos="bottom"):
    """곡 진행바 트랙의 좌우 여백/크기/y 좌표 (순수 함수, top/bottom 공용).
    바 폭은 PROGRESS_BAR_WIDTH_FRAC 비율로 가운데 정렬(레퍼런스 샘플 실측 기반).
    반환: (margin_x, bar_w, bar_h, y)."""
    margin_x = int(round(W * (1 - PROGRESS_BAR_WIDTH_FRAC) / 2))
    bar_w = max(10, W - margin_x * 2)
    bar_h = max(8, int(round(10 * scale)))
    if pos == "top":
        y = int(round(34 * scale))
    else:
        y = H - bar_h - int(round(26 * scale))
    return margin_x, bar_w, bar_h, y


def pill_alpha_expr(w, h, opacity, fill_expr=None):
    """가로 알약(스타디움) 모양 alpha 표현식 (geq 용).
    make_disc_png/make_vinyl_png 의 hypot 원형 마스킹 패턴을, X 를 [r, w-r] 로
    클램프해 '직선 구간은 그대로, 양 끝은 반원'인 알약 모양으로 확장한 것.

    fill_expr 를 주면(시간에 따라 자라는 ffmpeg 표현식, 예: 'W*clip(T/dur,0,1)')
    그 x 좌표까지만 채워 왼쪽에서 자라는 진행바 필(오른쪽 반원 끝이 곧 '손잡이'
    처럼 보인다)을 만든다. 생략하면 폭 전체를 채운 고정 트랙이 된다."""
    r = h / 2.0
    cy = (h - 1) / 2.0
    amp = int(round(255 * opacity))
    if fill_expr is None:
        clamp_x = f"clip(X,{r:.2f},{max(r, w - r):.2f})"
        dist = f"hypot(X-{clamp_x},Y-{cy:.2f})"
        return f"{amp}*if(lte({dist},{r:.2f}),1,0)"
    clamp_x = f"clip(X,{r:.2f},max({r:.2f},{fill_expr}-{r:.2f}))"
    dist = f"hypot(X-{clamp_x},Y-{cy:.2f})"
    return f"{amp}*lte(X,{fill_expr})*lte({dist},{r:.2f})"


def subtitle_zone_y(lay, sub_pos="bottom", sub_size=1.0):
    """write_ass() 의 Alignment/MarginV 해석과 맞춰, 자막이 실제 화면에서 차지할
    y 범위(1줄 기준 근사치)를 (zone_top, zone_bottom) 으로 추정하는 순수 함수.
    실제 가사(cues)가 있는지와 무관하게 '레이아웃상 자막에 예약된 영역'으로
    취급한다 — margin_v 자체가 이미 cue 유무와 무관한 레이아웃 상수이기 때문.
    title_caption_geometry() 가 캡션이 이 영역과 겹치지 않게 배치하는 데 쓴다."""
    H = lay["H"]
    fontsize = max(1, int(round(lay["font_size"] * float(sub_size))))
    line_h = int(round(fontsize * 1.2))
    if sub_pos == "top":
        zone_top = int(H * 0.08)
        zone_bottom = zone_top + line_h
    elif sub_pos == "middle":
        zone_top = H // 2 - line_h // 2
        zone_bottom = H // 2 + line_h // 2
    else:  # "bottom" (기본) — Alignment=2, MarginV 는 화면 하단에서 잰다
        zone_bottom = H - lay["margin_v"]
        zone_top = zone_bottom - line_h
    return zone_top, zone_bottom


def title_caption_geometry(disc_active, D, cy, H, scale=1.0, pos="auto", sub_zone=None,
                            W=None, progress_bar=False, progress_bar_pos="bottom"):
    """상시 제목/아티스트 캡션의 글자 크기/y 좌표 (순수 함수).
    pos="auto"(기본): 디스크 모드면 디스크 바로 아래(인트로 카드와 같은 크기 감각),
    디스크가 꺼져 있으면 화면 상단(기본 위치인 하단 자막과 겹치지 않도록).
    pos="top": 디스크 활성 여부와 무관하게 항상 화면 상단(레퍼런스 lp_vinyl 샘플처럼
    디스크 위에 캡션을 두는 구도용).
    pos="bottom"(신규): pos="top" 의 상하 대칭 버전 — 화면 하단에 진행바+제목+
    아티스트를 하나의 타이트한 묶음으로 앵커한다(제품 오너 피드백: "제목/아티스트/
    진행바를 하나의 div 로 잡는다고 생각하고 ~10px 간격으로 붙여라"). top 과 마찬가지로
    진행바가 그 변의 가장자리에 가장 가깝게, 캡션(제목 위/아티스트 아래, 읽는 순서
    유지)은 진행바 안쪽에 온다. top 의 고정 40*scale 시작 여백과 대칭되도록, 진행바가
    없을 때는 아티스트 하단이 화면 하단에서 40*scale 만큼 떨어진 지점에 자연 착지한다.
    sub_zone: subtitle_zone_y() 가 반환하는 (zone_top, zone_bottom). disc 바로 아래
    자리(auto)가 이 구간과 겹치면, 디스크와 자막 사이 틈에 억지로 끼워 넣는 대신
    자막 영역보다 아래로 캡션을 내려 자막·캡션이 항상 분리되게 한다(디스크 크기와
    무관하게 항상 성립하는 결정론적 지오메트리 — 매직 오프셋이 아니다). 이 보정은
    pos="auto" 전용이다(아래 참고).

    W, progress_bar, progress_bar_pos: pos="top"/"bottom" 이면서 진행바도 같은 변에
    떠 있으면(예: --progress-bar --progress-bar-pos top --title-caption-pos top), 둘
    다 화면 가장자리 근처에 함께 쌓인다(실측 결과 겹치는 버그가 있었다 —
    sample/playscreen.png 재현 확인: 진행바 트랙 하단 y≈31, 캡션 상단 y≈27, 4px
    겹침). 진행바가 이 조건일 때만 캡션을 진행바 바로 안쪽(GAP=10*scale 여백)으로
    붙여 절대 겹치지 않게 한다. W 를 안 주거나 progress_bar 가 꺼져 있으면(기존
    호출부와 하위호환) 이 보정은 전혀 적용되지 않고 기존처럼 고정 40*scale 기준을
    그대로 쓴다.
    반환: (title_fontsize, artist_fontsize, title_y, artist_y_gap) — artist_y =
    title_y + artist_y_gap.

    글자 크기/줄간격/여백은 디자인 레퍼런스(sample/playlist_sample1.png, 1433x843)를
    PIL 로 실측한 값 기반이다:
      - 커버 정사각형 경계: x≈542~889, y≈218~564 (한 변 D_ref≈346px, gradient/edge
        검출로 4변 모두 확인)
      - 제목("My Friend") 글자 바운딩박스: y≈622~670 (높이 48px)
      - 아티스트("Mark Lee (마크리)") 글자 바운딩박스: y≈686~713 (높이 27px)
      - 제목 상단 -> 아티스트 상단 간격: 64px
      - 커버 하단(564) -> 제목 상단(622) 간격: 58px
    D_ref 대비 비율로 바꾸면 title_fs/D≈0.137, artist_fs/D≈0.077, art_gap/D≈0.183,
    cover_gap/D≈0.17 — 기존 상수(52/30, gap=ttl_fs*1.05, margin=26*scale 고정)는
    1080p 환산 D_ref(H*0.42≈453.6)에 대해 각각 ≈0.114/0.066/1.05배/≈0.057 밖에
    안 돼 레퍼런스보다 작고 촘촘하다. 아래 상수를 실측 비율에 맞춰 키운다."""
    ttl_fs = int(round(62 * scale))
    art_fs = int(round(35 * scale))
    # top/bottom 명시 배치 전용 타이트 간격(제품 오너 피드백: "제목/아티스트/진행바를
    # 하나의 div 로 잡는다고 생각하고" 붙여라) — pos="auto" 의 art_gap(아래 else/elif
    # 분기, ttl_fs*1.6)과는 완전히 별개 값이다(그 쪽은 절대 안 바꾼다). 10px 로 시작해
    # 18px 로 한 차례 키웠는데, 실제 렌더 리뷰 후 재요청으로 23px 로 한 번 더 소폭
    # 확대(이번엔 "이 정도면 됐다" 피드백 — DISC_RESERVED_GAP=32px 는 이 조정과
    # 무관하게 그대로 둔다). 여전히 pos="auto" 의 ttl_fs*1.6(≈99px)보다는 훨씬
    # 촘촘한 "한 묶음" 느낌을 유지한다.
    GAP = int(round(23 * scale))
    if pos == "top":
        ttl_y = int(round(40 * scale))
        if progress_bar and progress_bar_pos == "top" and W:
            _, _, pb_h, pb_y = progress_bar_geometry(W, H, scale, "top")
            ttl_y = max(ttl_y, pb_y + pb_h + GAP)
        art_gap = ttl_fs + GAP
    elif pos == "bottom":
        # top 의 상하 대칭: 아티스트(캡션 블록의 가장자리쪽 줄)가 진행바(같은 변에
        # 있으면 그 안쪽) 또는 화면 하단 여백(40*scale, top 의 고정 시작값과 대칭)에
        # 앵커되고, 제목은 그 위에 GAP 만큼 띄워 온다.
        art_bottom = H - int(round(40 * scale))
        if progress_bar and progress_bar_pos == "bottom" and W:
            _, _, pb_h, pb_y = progress_bar_geometry(W, H, scale, "bottom")
            art_bottom = min(art_bottom, pb_y - GAP)
        art_gap = ttl_fs + GAP
        art_y = art_bottom - art_fs
        ttl_y = art_y - art_gap
    elif disc_active:
        # 커버 하단 -> 캡션 여백 = D 의 ≈0.17배(레퍼런스 실측: 58px / D_ref 346px).
        # 고정 픽셀(구 26*scale)이 아니라 D 비례라야 해상도/커버 크기가 달라져도
        # 레퍼런스와 같은 '뚜렷한 틈' 느낌이 유지된다.
        ttl_y = cy + D // 2 + int(round(D * 0.17))
        # 제목-아티스트 줄 간격: ttl_fs 의 배수. 오늘 이미 1.05 -> 1.3 으로 한 차례
        # 키웠는데 제품 오너가 더 벌려 달라고 재요청("제목/아티스트 간격 더 벌려줘")
        # 해 1.3 -> 1.6 으로 추가 확대. (pos="auto" 전용값 — top/bottom 은 위에서 이미
        # GAP 기반 타이트 값으로 설정됨.)
        art_gap = int(round(ttl_fs * 1.6))
    else:
        ttl_y = int(round(40 * scale))
        art_gap = int(round(ttl_fs * 1.6))

    if pos == "auto" and disc_active and sub_zone is not None:
        sub_top, sub_bottom = sub_zone
        gap = int(round(16 * scale))
        cap_bottom = ttl_y + art_gap + art_fs
        overlaps = (ttl_y - gap) < sub_bottom and (cap_bottom + gap) > sub_top
        if overlaps:
            ttl_y = sub_bottom + gap

    return ttl_fs, art_fs, ttl_y, art_gap


def disc_vertical_reservation(H, scale, title_caption_on, title_caption_pos, cap_has_text,
                               progress_bar_on, progress_bar_pos, W):
    """상/하단에 '고정 오버레이 묶음'(진행바 +/또는 제목+아티스트 캡션)이 실제로
    차지하는 세로 폭을 변(top/bottom)별로 독립적으로 계산하는 순수 함수.

    title_caption_geometry(pos="top"/"bottom") 와 progress_bar_geometry() 를 그대로
    재사용해 요소 높이를 구한다(상수 중복 정의 금지) — 두 변의 묶음 모두 "그 변에
    실제로 배치된 조합"만 반영한다: 캡션이 top 이면 top 변에, progress_bar_pos 가
    bottom 이면(캡션과 무관하게) bottom 변에 각각 독립적으로 반영된다. 즉 한쪽 변의
    캡션이 반대쪽 변의 '캡션 없는 진행바 단독'을 예약 대상에서 배제하지 않는다 —
    다만 이 함수를 호출할지 여부 자체(= 전체 예약 시스템의 on/off)는 호출부(render/
    main) 가 title_caption_pos 가 "top"/"bottom" 로 명시되고 실제 캡션 텍스트가 있을
    때만 결정한다(pos="auto" 이거나 캡션이 꺼져 있으면 절대 호출하지 않는다 — 이 함수
    자체는 그 게이트를 모른다).

    반환: (reserved_top, reserved_bottom).
      reserved_top    = 상단 묶음이 화면 맨 위(y=0)에서부터 차지하는 절대 y 좌표
                         (묶음 바로 아래 경계). 아무것도 없으면 0.
      reserved_bottom = 하단 묶음이 화면 맨 아래(y=H)에서부터 위로 차지하는 '높이'
                         (호출부는 H - reserved_bottom 으로 절대 y 좌표를 구한다).
                         아무것도 없으면 0.
    """
    cap_active = bool(title_caption_on and cap_has_text)

    reserved_top = 0
    cap_top = cap_active and title_caption_pos == "top"
    pb_top = bool(progress_bar_on and progress_bar_pos == "top")
    if cap_top:
        _, art_fs, ttl_y, art_gap = title_caption_geometry(
            False, 0, 0, H, scale, pos="top", W=W,
            progress_bar=pb_top, progress_bar_pos="top")
        reserved_top = ttl_y + art_gap + art_fs
    elif pb_top and W:
        _, _, pb_h, pb_y = progress_bar_geometry(W, H, scale, "top")
        reserved_top = pb_y + pb_h

    reserved_bottom = 0
    cap_bottom_on = cap_active and title_caption_pos == "bottom"
    pb_bottom = bool(progress_bar_on and progress_bar_pos == "bottom")
    if cap_bottom_on:
        _, art_fs, ttl_y, art_gap = title_caption_geometry(
            False, 0, 0, H, scale, pos="bottom", W=W,
            progress_bar=pb_bottom, progress_bar_pos="bottom")
        reserved_bottom = H - ttl_y
    elif pb_bottom and W:
        _, _, pb_h, pb_y = progress_bar_geometry(W, H, scale, "bottom")
        reserved_bottom = H - pb_y

    return reserved_top, reserved_bottom


# 예약된 변(캡션/진행바 묶음이 실제로 있는 변) 경계 -> 디스크 가장 가까운 바깥쪽
# 테두리까지 유지할 간격. 처음엔 프레임 기본 여백(15*scale)을 그대로 재사용했는데,
# 실제 렌더(sample/playscreen_top.png, sample/playscreen_bottom.png)를 제품 오너가
# 보고 확인한 버그: disc_avail_zone() 이 만든 [avail_top, avail_bottom] 전체 구간의
# '정중앙'에 디스크를 놓다 보니(cy = (avail_top+avail_bottom)//2), 디스크 지름이
# 보통 그 구간보다 작아서 남는 여유가 캡션 쪽과 반대쪽에 반씩 나뉘어 들어갔다 —
# 캡션과 맞닿은 쪽 간격이 15px 는커녕 프레임 높이의 10~17% 에 달하는 큰 여백으로
# 보였다(피드백: "간격이 너무 커"). 해결책은 두 가지를 분리하는 것:
#   1) 한쪽 변만 예약되어 있으면(top 또는 bottom 단독) '중앙정렬' 대신 '앵커' —
#      디스크의 그 변 쪽 바깥 테두리를 예약 경계에서 이 간격만큼만 띄운다. 반대쪽
#      (예약 없는 쪽)에 남는 여유는 자연스럽게 그대로 둔다(문제 없음, 원래도 여긴
#      캡션이 없어 넓어 보이는 게 정상).
#      -> 이 상수가 바로 그 "이 간격": 15px 는 1080p 기준 거의 안 보이는 수준이라
#         제품 오너 피드백("붙으면 안되지만, 진짜 적당히 살짝 떨어져서 이쁘게")에
#         맞춰 2배 이상(32px 레퍼런스)으로 키웠다 — disc_avail_zone() 의 프레임
#         기본 마진(margin, 캡션이 전혀 없을 때 '그냥 프레임 가장자리에서 15px'
#         용도)과는 별개 상수다: 프레임 가장자리 여백과 '캡션 블록에 붙지 않기
#         위한 여백'은 의미가 다르므로 값도 따로 관리한다.
#   2) 양쪽 변이 모두 예약되어 있으면(예: 진행바 top + 캡션 bottom) '앵커'할 단일
#      기준면이 없으므로 그 사이 정중앙에 놓는다(기존 방식 유지, 이 경우엔 애초에
#      남는 여유가 양쪽에 자연히 나뉘는 게 맞는 구도라 버그가 아니었다).
DISC_RESERVED_GAP = 32


def disc_avail_zone(H, W, scale, title_caption_on, title_caption_pos, cap_has_text,
                     progress_bar_on, progress_bar_pos, duration):
    """디스크(+비닐/링)가 세로로 놓일 수 있는 구간 [avail_top, avail_bottom] 을 구하는
    순수 함수. render()/main() 양쪽에서 재사용해 '디스크 재배치'와 'D 축소(오버플로
    방지)' 계산의 기준을 하나로 통일한다(따로 계산하면 어긋나기 쉽다).

    title_caption_pos 가 "top"/"bottom" 로 명시되고 실제로 캡션 텍스트가 있을 때만
    disc_vertical_reservation() 의 예약 영역을 반영한다 — 그 변이 실제로 예약되어
    있으면(reserved_top/reserved_bottom > 0) DISC_RESERVED_GAP(캡션 블록에 너무
    붙지 않기 위한 여백), 그 변에 아무것도 없으면(반대쪽 변만 예약된 '한쪽만' 케이스)
    순수 프레임 마진(15*scale, margin)을 각 변에 독립적으로 적용한다. title_caption_pos
    가 "auto" 이거나 title_caption 이 꺼져 있거나 예약 영역이 서로 겹쳐 여유가 없는
    예외 상황에는 예약을 전혀 적용하지 않고 순수 프레임 마진(margin, H-margin)만
    반환한다.

    반환: (avail_top, avail_bottom, top_reserved, bottom_reserved).
      top_reserved/bottom_reserved 는 그 변에 실제로 진행바/캡션 묶음이 예약되어
      있는지를 각각 나타낸다 — 호출부(render())는 이 두 플래그로 '한쪽 변만
      예약되어 있으면 그 변에 디스크를 앵커하고, 양쪽 다 예약되어 있으면 그 사이
      정중앙에 놓고, 둘 다 아니면(=예외/미예약) 기존 base_cy 를 그대로 쓰는'
      판단을 내린다(회귀 방지 — reserved 가 모두 False 인데 cy 를 건드리면
      pos="auto"/캡션-꺼짐 경로의 기존 동작이 깨진다). D 축소 계산에는 이 플래그와
      무관하게 항상 avail_top/avail_bottom 을 그대로 쓴다(예약이 없을 때도 15px
      프레임 마진은 항상 지켜야 하므로)."""
    margin = int(round(15 * scale))
    reserved_gap = int(round(DISC_RESERVED_GAP * scale))
    pb_will_draw = bool(progress_bar_on and duration)
    cap_will_draw = bool(title_caption_on and cap_has_text)
    if cap_will_draw and title_caption_pos in ("top", "bottom"):
        reserved_top, reserved_bottom = disc_vertical_reservation(
            H, scale, title_caption_on, title_caption_pos, cap_has_text,
            pb_will_draw, progress_bar_pos, W)
        top_reserved = reserved_top > 0
        bottom_reserved = reserved_bottom > 0
        avail_top = reserved_top + (reserved_gap if top_reserved else margin)
        avail_bottom = H - reserved_bottom - (reserved_gap if bottom_reserved else margin)
        if avail_top < avail_bottom:
            return avail_top, avail_bottom, top_reserved, bottom_reserved
    return margin, H - margin, False, False


def disc_stack_layout(H, scale, reserved_top, reserved_bottom, top_reserved, bottom_reserved, D,
                       sub_zone=None):
    """상단 묶음(진행바/캡션) · 디스크 · 하단 묶음을 "실제로 존재하는 요소만"
    하나의 강체 스택으로 보고, 그 스택 전체를 프레임 세로 중앙에 오도록 이동량
    (stack_shift)과 디스크 중심(cy)을 함께 계산하는 순수 함수.

    버그 재현(sample/screen.png, --disc-theme lp_vinyl --title-caption-pos
    bottom): 이전 코드는 디스크를 하단 묶음에서 DISC_RESERVED_GAP 만큼만 띄워
    앵커하고(disc_avail_zone()/render() 의 옛 elif bottom_reserved 분기), 나머지
    모든 여유 공간을 반대쪽(위)에 몰아넣었다 — 화면 위쪽에 거대한 빈 공간이 남고
    디스크+캡션 조합 전체가 하단에 짓눌려 보였다. 이 함수는 "묶음+간격+디스크
    (+간격+묶음)" 전체 폭(stack_h)을 구해 프레임에서 정중앙으로 옮긴다 — 상단만/
    하단만/양쪽 다 예약된 세 경우 모두 같은 공식 하나로 처리한다(양쪽 다 예약된
    경우는 대수적으로 기존 '두 예약 경계 사이 중앙' 공식과 디스크 cy 가 완전히
    동일하게 나온다 — 유일한 차이는 상/하단 묶음 자체도 이제 여유가 있으면
    프레임 가장자리에서 안쪽으로 함께 이동한다는 점이며, 이는 의도된 개선이다).

    reserved_top/reserved_bottom: disc_vertical_reservation() 이 돌려주는 값
    그대로(각 변 묶음의 실제 높이, 없으면 0). top_reserved/bottom_reserved 도
    disc_avail_zone() 과 같은 의미의 플래그.

    반환: (stack_shift, cy). 둘 다 예약이 전혀 없으면(top_reserved 와
    bottom_reserved 가 모두 False) (0, None) — 호출부는 cy=None 이면 반드시
    기존 base_cy 를 그대로 써야 한다(회귀 방지 — pos="auto"/캡션 꺼짐 경로는
    top_reserved/bottom_reserved 자체가 항상 False 이므로 이 함수를 호출해도
    안전하게 no-op).

    stack_shift 사용법(중요 — render() 의 실제 진행바/캡션 draw 호출부가 반드시
    이 값과 같은 방식으로 어긋남 없이 적용해야, "예측"(이 함수)과 "실제 그리기"가
    항상 일치한다):
      - 상단 묶음(progress_bar_geometry/title_caption_geometry 를 pos="top" 으로
        호출해 얻은 y 값)에는 stack_shift 를 그대로 더한다(두 함수 모두 top 분기는
        H 와 무관한 고정 상수 기반이라 덧셈으로만 아래로 밀 수 있다).
      - 하단 묶음에는 H 대신 (H - stack_shift) 를 두 함수에 넘긴다(두 함수의 모든
        bottom 분기가 "H - 상수" 형태이므로, H 를 줄이면 정확히 그만큼 위로 밀린
        결과와 대수적으로 동일하다 — 새 매개변수를 추가하지 않고 기존 H 인자를
        재사용하는 방식).

    sub_zone: subtitle_zone_y() 가 반환하는 (zone_top, zone_bottom), 자막(가사)
    안전영역. round 6 자체 검증 중 발견(제품 오너가 보고한 버그는 아님): 상/하단
    묶음이 스택 중앙정렬로 안쪽(프레임 중앙 쪽)으로 이동하다가 — 특히 여유가
    많을 때, 즉 원래 버그가 가장 심했던 바로 그 상황에서 — 자막 영역을 침범할
    수 있다(title_caption_geometry() 의 sub_zone 회피는 원래 pos="auto" 전용이라
    "top"/"bottom" 명시 배치는 대상이 아니었다 — 이전엔 두 묶음이 프레임
    가장자리에 고정돼 있어 문제가 안 됐지만, 이제는 이동하므로 새로 생긴 충돌
    가능성이다). sub_zone 을 주면 stack_shift 를 필요한 만큼만 줄여(0 이 하한)
    하단 묶음이 자막 영역 아래쪽을, 상단 묶음이 자막 영역 위쪽을 침범하지 않게
    한다 — 두 묶음 모두 같은 stack_shift 를 공유하므로 이 클램프도 디스크 cy 에
    자동으로 반영되어 여기서도 어긋남이 생기지 않는다."""
    if not (top_reserved or bottom_reserved):
        return 0, None
    gap = int(round(DISC_RESERVED_GAP * scale))
    stack_h = D
    if top_reserved:
        stack_h += reserved_top + gap
    if bottom_reserved:
        stack_h += reserved_bottom + gap
    stack_shift = max((H - stack_h) // 2, 0)

    if sub_zone is not None:
        sub_top, sub_bottom = sub_zone
        sub_gap = int(round(16 * scale))  # pos="auto" 의 기존 sub_zone 여백(16*scale)과 동일
        if bottom_reserved:
            # 하단 묶음의 이동 후 위쪽 경계가 자막 영역 아래쪽을 침범하지 않게.
            group_top_edge = H - reserved_bottom - stack_shift
            if group_top_edge < sub_bottom + sub_gap:
                max_shift = max(H - reserved_bottom - sub_bottom - sub_gap, 0)
                stack_shift = min(stack_shift, max_shift)
        if top_reserved:
            # 상단 묶음의 이동 후 아래쪽 경계가 자막 영역 위쪽을 침범하지 않게.
            group_bottom_edge = reserved_top + stack_shift
            if group_bottom_edge > sub_top - sub_gap:
                max_shift = max(sub_top - sub_gap - reserved_top, 0)
                stack_shift = min(stack_shift, max_shift)

    x = (reserved_top + gap) if top_reserved else 0
    cy = stack_shift + x + D // 2
    return stack_shift, cy


def disc_theme_max_extent(D, disc_theme):
    """테마별 디스크 조합의 최대 세로 확장치 — classic 은 D 그대로, square_spin 은
    45도 회전 대각선(D*sqrt(2)), lp_vinyl 은 커버(D*LP_VINYL_SIZE_SCALE, 비닐보다
    큼), text_ring 은 텍스트 링(D*TEXT_RING_SCALE, 커버보다 큼). 모든 테마의
    오버레이가 cy 를 중심으로 대칭 배치되므로(overlay y = cy - extent//2), 이
    확장치의 절반이 곧 'cy 에서 그 조합의 바깥 테두리까지의 거리'이기도 하다 —
    disc_shrink_factor() 의 축소 비율 계산과 render() 의 단일 변 앵커 배치(근접
    테두리까지의 절반 거리) 양쪽에서 재사용한다(따로 계산하면 어긋나기 쉽다)."""
    if disc_theme == "square_spin":
        max_extent = int(math.ceil(D * math.sqrt(2)))
        max_extent += max_extent % 2
    elif disc_theme == "lp_vinyl":
        max_extent = int(D * LP_VINYL_SIZE_SCALE)
        max_extent -= max_extent % 2
    elif disc_theme == "text_ring":
        max_extent = int(D * TEXT_RING_SCALE)
        max_extent -= max_extent % 2
    else:
        max_extent = D
    return max_extent


def disc_shrink_factor(D, avail_top, avail_bottom, disc_theme):
    """디스크/비닐/링 조합이 [avail_top, avail_bottom] 세로 구간을 넘지 않도록 D 에
    곱할 축소 배율(0 < factor <= 1.0)을 계산하는 순수 함수. 테마별 최대 세로
    확장치는 disc_theme_max_extent() 를 재사용한다(중복 정의 금지).

    main() 의 PNG 프리패스와 render() 의 오버레이 배치 양쪽에서 반드시 이 함수
    하나만 호출해야 한다 — 각자 따로 계산하면 LP_VINYL_SIZE_SCALE 프리패스/오버레이
    공식 불일치(주석 참고)와 같은 종류의 크기 불일치 버그가 재발한다."""
    vzone = max(avail_bottom - avail_top, 1)
    max_extent = disc_theme_max_extent(D, disc_theme)
    if max_extent <= vzone or max_extent <= 0:
        return 1.0
    return vzone / max_extent


def lp_vinyl_cover_center_x(W, D_lp, VD, off_x):
    """lp_vinyl 테마의 커버+비닐 '조합' 바운딩박스를 프레임 가로 중앙(W/2)에 맞추는
    커버 중심 x좌표(cover_cx)를 구하는 순수 함수. 비닐 중심 x 는 cover_cx + off_x.

    off_x 는 부호 있는 값(양수=비닐이 커버 중심 기준 오른쪽으로, 음수=왼쪽으로
    삐져나옴 — --disc-lp-side 의 "right"/"left" 에 대응). 어느 쪽이 조합의 바운딩
    박스 경계를 결정하는지 하드코딩하지 않고, 커버/비닐 각 변의 좌표를 min/max 로
    비교해 바운딩박스를 구하므로 좌/우 어느 방향의 off_x 를 넣어도(그리고 향후
    LP_VINYL_OFFSET/LP_VINYL_OFFSET_NUDGE_PX/LP_VINYL_SCALE 값이 바뀌어도) 항상
    정확히 중앙정렬된 cover_cx 를 돌려준다.

    유도: cover_cx=0 기준 상대 좌표로 커버/비닐 각 변을 구해 bbox_left/right 를
    잡은 뒤(rel_cover_*, rel_vinyl_*), 그 bbox 의 중점이 W/2 가 되도록 cover_cx 를
    풀면 cover_cx = W/2 - (rel_bbox_left + rel_bbox_right) / 2."""
    rel_cover_left, rel_cover_right = -D_lp // 2, D_lp // 2
    rel_vinyl_left, rel_vinyl_right = off_x - VD // 2, off_x + VD // 2
    rel_bbox_left = min(rel_cover_left, rel_vinyl_left)
    rel_bbox_right = max(rel_cover_right, rel_vinyl_right)
    return W // 2 - (rel_bbox_left + rel_bbox_right) // 2


def add_square_shadow(parts, cur, size, x, y, fps, label):
    """정사각 커버(cover_png) 뒤에 깔 소프트 드롭섀도우 (lp_vinyl/text_ring 전용).

    디자인 레퍼런스(sample/playlist_sample1.png)를 PIL 로 실측: 커버 하단 바로
    바깥은 상단보다 뚜렷하게 어둡고(위: 89 vs 91, 거의 무차이 / 아래: 67 vs
    100px 더 아래 192, 뚜렷한 낙차), 좌우는 그 중간(좌 128->140, 우 58->63).
    배경이 복잡한 보케 사진이라 100px 낙차 자체를 그대로 재현하면(D 대비
    ≈29%) '은은한 드롭섀도우'가 아니라 비네트에 가까워지므로, 절대 낙차폭이
    아니라 '위쪽은 거의 안 보이고 아래쪽만 뚜렷이 보인다'는 방향성만 취한다.

    처음 버전은 offset_y 를 size 의 2.5%(고정 비율)로만 살짝 내렸는데, pad
    (블러 캔버스 여유폭)가 sigma 의 ~1.6배뿐이라 gblur 가 캔버스 경계에서
    잘려(하드 클립) 위/아래 모두 15~20px 만에 사라지는 버그가 있었다 —
    렌더 결과(f5_flat.png)를 같은 방식으로 실측해 발견. 고쳐야 할 두 가지:
      1) pad 를 sigma 의 배수(3배)로 잡아 gblur 가 캔버스 밖에서 잘리지
         않고 자연스러운 가우시안 낙차를 다 그릴 수 있게 한다.
      2) offset_y = pad 로 두면(고정 비율이 아니라 pad 그 자체) 섀도우
         사각형의 흐려진 윗부분이 정확히 커버 뒤로 완전히 숨고(위쪽 노출
         ≈0, 레퍼런스의 '위 89 vs 91 무차이'와 정확히 대응), 아랫부분은
         2*pad 만큼 고스란히 드러난다(레퍼런스의 '아래쪽만 뚜렷' 대응) —
         매직 넘버가 아니라 pad 자체의 기하학적 성질에서 오프셋이 정해진다.

    정사각 커버라 실제 알파 마스크가 필요 없으므로(make_disc_png 처럼
    원형이 아님) color+geq 로 사각 알파를 굽고 gblur 로 가장자리를 부드럽게
    편 뒤, 실제 커버보다 먼저(밑에) 합성한다.

    size: 커버 한 변(px, 이미 D/D_lp 등 최종 렌더 크기). x, y: 커버가 실제
    overlay 되는 좌상단 좌표. fps: 프레임레이트(color 소스용). label: 파이프라인
    라벨 충돌을 피하기 위한 접미사(테마별로 다르게 호출).
    반환: 섀도우가 합성된 새 파이프라인 라벨(다음 오버레이의 입력으로 사용)."""
    sigma = max(4, int(round(size * 0.035)))    # 블러 반경 (레퍼런스: 완만한 낙차)
    pad = max(sigma * 3, int(round(size * 0.10)))  # gblur 가 캔버스 밖에서 안 잘릴 여유
    offset_y = pad                              # 위=커버 뒤로 완전히 숨음, 아래=2*pad 노출
    opacity = 0.45
    canvas = size + pad * 2
    amp = int(round(255 * opacity))
    a_expr = f"{amp}*between(X,{pad},{pad + size - 1})*between(Y,{pad},{pad + size - 1})"
    parts.append(
        f"color=c=black:s={canvas}x{canvas}:r={fps},format=gbrap,"
        f"geq=r=0:g=0:b=0:a='{a_expr}',gblur=sigma={sigma}[shsrc_{label}]")
    sx = x - pad
    sy = y - pad + offset_y
    out_label = f"[vsh_{label}]"
    parts.append(f"{cur}[shsrc_{label}]overlay={sx}:{sy}{out_label}")
    return out_label


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


def make_square_png(src, out_path, size):
    """앨범아트 -> 단순 정사각 크롭 PNG (마스킹/테두리 없음, 프리패스 1프레임).
    lp_vinyl / text_ring 테마의 정적 커버 이미지로 쓴다."""
    D = size - (size % 2)
    vf = f"scale={D}:{D}:force_original_aspect_ratio=increase,crop={D}:{D}"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", os.path.abspath(src),
           "-vf", vf, "-frames:v", "1", os.path.abspath(out_path)]
    if run(cmd).returncode != 0:
        sys.exit("레코드 모드(lp_vinyl/text_ring): 앨범아트 정사각 크롭 실패")


def make_default_cover_png(out_path, size, accent_hex):
    """레코드 모드용 앨범아트가 전혀 없을 때(--disc-art 도 --bg 도 없음) 대신 쓰는
    기본 커버: 그라데이션(배경의 gradients 소스와 동일 패턴) + ♪ 아이콘. Pillow 등
    추가 의존성 없이 순수 ffmpeg(gradients lavfi + symbol_font_spec 의 drawtext)만
    사용 — make_disc_png/make_square_png 가 다른 --disc-art 처럼 그대로 크롭·
    마스킹할 수 있도록 '이미지 파일'로 생성해 둔다."""
    D = size - (size % 2)
    c0 = norm_hex(accent_hex, DEFAULT_VIZ_COLORS[0])
    c1 = norm_hex(DEFAULT_VIZ_COLORS[1], DEFAULT_VIZ_COLORS[1])
    fs = int(D * 0.42)
    vf = (f"drawtext={symbol_font_spec()}:text='♪':fontcolor=white@0.8:"
          f"fontsize={fs}:x=(w-tw)/2:y=(h-th)/2")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
           "-i", f"gradients=s={D}x{D}:c0=0x{c0}:c1=0x{c1}:nb_colors=2",
           "-vf", vf, "-frames:v", "1", os.path.abspath(out_path)]
    if run(cmd).returncode != 0:
        sys.exit("레코드 모드: 기본 커버(앨범아트 없음) 생성 실패")


def vinyl_shading_expr(x_expr, y_expr, c, R, label_r):
    """비닐 표면에 입체감(대각선 하이라이트 시트 + 라벨/외곽 이너섀도우)을 주는
    geq 가산(additive) 밝기 보정식 — make_vinyl_png() 의 그루브/라벨 패스가
    공통으로 더해 쓴다(그래야 그루브 위에서 만든 빛과 라벨 위 빛이 같은 방향으로
    보인다). x_expr/y_expr 는 '이 픽셀이 비닐 전체 기준으로 어디에 있는지'를
    나타내는 좌표식 — 그루브 패스는 전체 캔버스라 그냥 "X"/"Y", 라벨 패스는
    자기 크기의 별도 캔버스에서 실행되므로 오프셋을 더한 "X+off" 식으로 넘긴다.

    - highlight: 원반 대각선을 가로지르는 부드러운 밝은 띠 — 실제 레코드 사진에서
      흔한, 조명이 원반 표면에 비스듬히 반사되는 모습을 흉내(가우시안 형태,
      exp(-x^2) 로 감쇠).
    - rim_shadow: 바깥 가장자리(R*0.82~R)로 갈수록 어두워지는 완만한 이너섀도우
      — 원반이 평평한 인쇄가 아니라 살짝 굴곡진 것처럼 보이게 한다.
    - label_shadow: 라벨 스티커 바로 바깥 테두리를 살짝 어둡게 눌러 라벨이
      비닐 표면에서 한 겹 얹혀 있는 것처럼 보이게 한다.
    은은한 배경 장식 요소이므로 진폭은 작게(±40 이내) 유지한다."""
    gd = f"hypot(({x_expr})-{c:.1f},({y_expr})-{c:.1f})"
    diag = f"((({x_expr})-{c:.1f})+(({y_expr})-{c:.1f}))/{R * 1.4142:.1f}"
    highlight = f"42*exp(-pow(({diag}-0.35)*2.6,2))"
    rim_shadow = f"16*clip((({gd})-{R * 0.82:.1f})/{R * 0.18:.1f},0,1)"
    label_shadow = f"12*exp(-pow((({gd})-{label_r + 5:.1f})/7,2))"
    return f"({highlight}-{rim_shadow}-{label_shadow})"


def make_vinyl_png(out_path, size, accent_hex, art_src=None):
    """검은 바이닐(LP) 텍스처 PNG (프리패스, 1프레임 — 추가 의존성 없음).
    동심원 그루브(radius-distance 사인 변조, make_disc_png 의 hypot 링 패턴과
    radial 헤일로의 a_expr 패턴을 재사용)와 중앙 라벨 원, 스핀들 홀을 그린다.
    바깥 가장자리는 make_disc_png 와 동일한 소프트 알파 낙차로 마감한다.
    vinyl_shading_expr() 로 대각선 하이라이트 + 이너섀도우를 얹어 평면적으로
    보이지 않게 한다("입체감" 피드백 — 렌더 프레임 비교로 확인).

    art_src: 주어지면(레퍼런스 sample/palylist_sample2.png 처럼) 라벨 자리를 flat
    accent 색이 아니라 실제 앨범아트를 원형으로 크롭한 이미지로 채운다 — 비닐
    PNG 전체가 rotate 로 통째로 회전하므로 라벨 속 아트도 자연히 비닐과 같이
    돈다(요청사항 그 자체). art_src 가 없으면(폴백) 기존처럼 flat accent 색."""
    D = size - (size % 2)
    c = (D - 1) / 2
    R = D / 2 - 2                      # 소프트 엣지 여유 (make_disc_png 와 동일 패턴)
    label_r = D * 0.22                 # 중앙 라벨(스티커) 반지름
    hole_r = max(3.0, D * 0.035)       # 스핀들 홀 반지름
    dist = f"hypot(X-{c:.1f},Y-{c:.1f})"
    # 동심원 그루브: 반지름 거리에 따라 명암이 주기적으로 흔들리는 회색조 링들
    groove = f"(22+14*sin({dist}*1.05))"
    in_hole = f"lt({dist},{hole_r:.1f})"
    a_expr = f"255*clip(({R:.1f}-{dist})/2+1,0,1)"
    shade = vinyl_shading_expr("X", "Y", c, R, label_r)

    if not art_src or not os.path.exists(art_src):
        # 폴백: 아트가 없으면 기존처럼 라벨을 flat accent 색으로 채운다(입체감
        # 셰이딩은 그루브/라벨 모두에 동일하게 적용해 빛 방향이 이어지게 한다).
        accent = norm_hex(accent_hex, DEFAULT_VIZ_COLORS[0])
        ar, ag, ab = int(accent[0:2], 16), int(accent[2:4], 16), int(accent[4:6], 16)
        in_label = f"lt({dist},{label_r:.1f})"
        r_expr = f"if({in_hole},6,clip(if({in_label},{ar},{groove})+{shade},0,255))"
        g_expr = f"if({in_hole},6,clip(if({in_label},{ag},{groove})+{shade},0,255))"
        b_expr = f"if({in_hole},6,clip(if({in_label},{ab},{groove})+{shade},0,255))"
        vf = (f"format=gbrap,"
              f"geq=r='{r_expr}':g='{g_expr}':b='{b_expr}':a='{a_expr}'")
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
               "-i", f"color=c=black:s={D}x{D}:r=1",
               "-vf", vf, "-frames:v", "1", os.path.abspath(out_path)]
        if run(cmd).returncode != 0:
            sys.exit("레코드 모드(lp_vinyl): 비닐 텍스처 생성 실패")
        return

    # ---- art_src 있음: 그루브 베이스 -> 라벨 자리에 원형 크롭 아트 오버레이 ->
    #      스핀들 홀을 마지막에 다시 뚫는 3단 프리패스 ----
    out_abs = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_abs) or "."
    stem = os.path.splitext(os.path.basename(out_abs))[0]
    base_tmp = os.path.join(out_dir, f"_{stem}_base.png")
    label_tmp = os.path.join(out_dir, f"_{stem}_label.png")
    combined_tmp = os.path.join(out_dir, f"_{stem}_combo.png")
    try:
        # 1) 그루브만 있는 베이스(라벨/홀 구분 없이 전면 그루브 — 라벨 위에도
        #    이음매 없이 이어지다가 아트로 완전히 덮인다). 셰이딩도 여기서 같이 굽는다.
        base_vf = (f"format=gbrap,"
                   f"geq=r='clip({groove}+{shade},0,255)':"
                   f"g='clip({groove}+{shade},0,255)':"
                   f"b='clip({groove}+{shade},0,255)':a='{a_expr}'")
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
               "-i", f"color=c=black:s={D}x{D}:r=1",
               "-vf", base_vf, "-frames:v", "1", base_tmp]
        if run(cmd).returncode != 0:
            sys.exit("레코드 모드(lp_vinyl): 비닐 그루브 베이스 생성 실패")

        # 2) 라벨 자리를 채울 원형 크롭 아트 (make_disc_png 와 동일한 소프트
        #    엣지 원형 마스킹 패턴, 링 없이 단순 원). 라벨은 자기 크기(label_d)의
        #    별도 캔버스에서 크롭되므로, 그루브 베이스와 같은 방향의 빛으로
        #    보이려면 로컬 좌표(X,Y)에 오프셋(off)을 더해 비닐 전체 기준 좌표로
        #    바꾼 뒤 셰이딩식에 넣어야 한다 — off 는 3)에서 합성할 위치와 동일.
        label_d = max(8, int(round(label_r * 2)))
        label_d -= label_d % 2
        lc = (label_d - 1) / 2
        lR = label_d / 2 - 1
        off = (D - label_d) // 2  # 그루브 베이스 중앙에 합성될 오프셋(3 에서 재사용)
        label_a_expr = f"255*clip(({lR:.1f}-hypot(X-{lc:.1f},Y-{lc:.1f}))/2+1,0,1)"
        label_shade = vinyl_shading_expr(f"X+{off}", f"Y+{off}", c, R, label_r)
        label_vf = (
            f"scale={label_d}:{label_d}:force_original_aspect_ratio=increase,"
            f"crop={label_d}:{label_d},format=gbrap,"
            f"geq=r='clip(r(X,Y)+{label_shade},0,255)':"
            f"g='clip(g(X,Y)+{label_shade},0,255)':"
            f"b='clip(b(X,Y)+{label_shade},0,255)':a='{label_a_expr}'"
        )
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", os.path.abspath(art_src),
               "-vf", label_vf, "-frames:v", "1", label_tmp]
        if run(cmd).returncode != 0:
            sys.exit("레코드 모드(lp_vinyl): 라벨 아트 크롭 실패")

        # 3) 라벨 아트를 그루브 베이스 중앙에 합성
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-i", base_tmp, "-i", label_tmp,
               "-filter_complex", f"[0:v][1:v]overlay={off}:{off}:format=auto",
               "-frames:v", "1", combined_tmp]
        if run(cmd).returncode != 0:
            sys.exit("레코드 모드(lp_vinyl): 라벨 아트 합성 실패")

        # 4) 스핀들 홀은 아트 위에서도 항상 보여야 하므로 마지막에 다시 뚫는다
        #    (r(X,Y)/g(X,Y)/b(X,Y)/alpha(X,Y) 로 나머지 영역은 그대로 통과시키는
        #    패턴은 make_disc_png 의 ring 오버레이 트릭과 동일 — 참고: geq 에서
        #    알파 평면 교차 참조 함수명은 'a(X,Y)'가 아니라 'alpha(X,Y)'다) ----
        hole_vf = (
            f"format=gbrap,"
            f"geq=r='if({in_hole},6,r(X,Y))':g='if({in_hole},6,g(X,Y))':"
            f"b='if({in_hole},6,b(X,Y))':a='if({in_hole},255,alpha(X,Y))'"
        )
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", combined_tmp,
               "-vf", hole_vf, "-frames:v", "1", out_abs]
        if run(cmd).returncode != 0:
            sys.exit("레코드 모드(lp_vinyl): 스핀들 홀 생성 실패")
    finally:
        for tmp in (base_tmp, label_tmp, combined_tmp):
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass


_DEFAULT_RING_PHRASE = "MUSIC EVERYWHERE - "

# 구분자로 흔히 쓰는 '•'(U+2022)/'·'(U+00B7)는 동봉 폰트 중 하나(Jua-Regular)에
# 글리프가 없어 각지고 빈 사각형(tofu)으로 깨진다 — 두 동봉 폰트 모두 갖고 있는
# ASCII 하이픈으로 대체해 어떤 폰트를 골라도 항상 정상 렌더된다.
_RING_SEP = " - "


def default_ring_text(title, artist):
    """text_ring 테마의 기본 텍스트: 제목/아티스트가 있으면 그걸로, 없으면
    일반 반복 문구로 폴백. make_ring_text_png 는 이 결과를 원 둘레만큼 반복한다."""
    title = (title or "").strip()
    artist = (artist or "").strip()
    if title and artist:
        return f"{title}{_RING_SEP}{artist}{_RING_SEP}"
    if title:
        return f"{title}{_RING_SEP}"
    if artist:
        return f"{artist}{_RING_SEP}"
    return _DEFAULT_RING_PHRASE


def make_ring_text_png(out_path, size, text, font_path):
    """커버 주위를 도는 곡선 텍스트 PNG (프리패스, text_ring 테마 전용).
    글자 단위 회전 배치가 필요해 순수 ffmpeg 로는 만들기 어려우므로, stable-ts 와
    같은 방식으로 Pillow 를 지연 임포트(opt-in 의존성)해서 렌더한다."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        sys.exit(
            "레코드 모드(text_ring 테마)에는 Pillow 가 필요합니다: "
            "pip install Pillow (텍스트 링 테마 전용, 기본 기능엔 불필요)"
        )

    D = size - (size % 2)
    img = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = max(12, int(D * 0.045)) + 3
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path and \
            os.path.exists(font_path) else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()

    radius = max(1.0, D / 2 - font_size * 0.9)
    circumference = 2 * math.pi * radius

    base = (text or "").strip() or _DEFAULT_RING_PHRASE
    if not base.endswith(" "):
        base += " "
    rendered = base
    # 둘레를 다 채울 때까지 문구 반복
    while draw.textlength(rendered, font=font) < circumference:
        rendered += base
    # 이음매에서 겹치지 않도록 둘레를 넘는 만큼 뒤에서 잘라낸다
    while len(rendered) > 1 and draw.textlength(rendered, font=font) > circumference:
        rendered = rendered[:-1]

    cx = cy = D / 2
    angle_deg = -90.0  # 12시 방향에서 시작해 시계방향으로
    pad = font_size * 1.5
    cell = int(pad * 2)
    for ch in rendered:
        ch_w = draw.textlength(ch, font=font)
        half_step_deg = (ch_w / radius) * (180.0 / math.pi) / 2.0
        theta = angle_deg + half_step_deg
        rad = math.radians(theta)
        x = cx + radius * math.cos(rad)
        y = cy + radius * math.sin(rad)

        glyph = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glyph)
        gdraw.text((pad, pad), ch, font=font, fill=(255, 255, 255, 255), anchor="mm")
        # 글자가 원 접선 방향(바깥을 향해 똑바로 서도록) 회전
        rotated = glyph.rotate(-(theta + 90.0), resample=Image.BICUBIC, expand=False)
        img.alpha_composite(rotated, (int(x - pad), int(y - pad)))

        angle_deg += half_step_deg * 2.0

    img.save(out_path)

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
           progress_bar_pos="bottom", progress_bar_color=None,
           sparkle=False, outro_cta=False, outro_cta_text="",
           disc_bg_style="off", disc_theme="classic", disc_ring_text=None,
           cover_png=None, vinyl_png=None, ring_png=None,
           title_caption=False, cap_title="", cap_artist="",
           title_caption_pos="auto", sub_pos="bottom", sub_size=1.0,
           disc_lp_side="right", disc_ring_side="left"):
    work_dir = os.path.dirname(os.path.abspath(ass_path)) or "."
    ass_name = os.path.basename(ass_path)
    W, H = lay["W"], lay["H"]

    # 레코드 모드 활성 여부: classic 은 disc_png, lp_vinyl/text_ring 은 cover_png 로 판단
    # (둘 다 build_bg 의 disc_bg_style(glow) 게이트와 radial 헤일로 게이트에 공통으로 쓰인다)
    disc_active = bool(disc_png) or bool(cover_png)
    # 진행바가 실제로 그려질지 여부(아래쪽 진행바 오버레이 블록의 게이트 조건과
    # 동일) — 상단 캡션/디스크 레이아웃 예약이 실제로 그려지지도 않을 진행바를
    # 위해 공간을 비워두지 않도록 이 조건을 공유한다.
    pb_will_draw = bool(progress_bar and duration)

    extra_inputs, bg_parts, bg_label, audio_idx = build_bg(
        bg_list, lay, duration, kenburns, bg_color, video_bg=video_bg,
        bg_style=bg_style, bg_grad=bg_grad,
        disc_bg_style=(disc_bg_style if disc_active else "off"))
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

    # ---- 레코드 모드: 앨범아트가 천천히 회전 (classic/lp_vinyl/text_ring, +선택: 배경 헤일로) ----
    # disc_ring_text 는 text_ring 프리패스(make_ring_text_png)가 이미 ring_png 에
    # 구워 넣으므로 여기선 쓰이지 않는다 — 호출부(main)와 시그니처를 맞추기 위해 받는다.
    disc_idx = None
    # 자막(가사) 안전영역 — disc_stack_layout() 의 스택 중앙정렬이 상/하단 묶음을
    # 안쪽으로 옮기다가 자막 영역을 침범하지 않도록 클램프하는 데 필요해서, 원래
    # title_caption 블록 안에서만 계산하던 것을 여기로 끌어올렸다(disc_active
    # 여부와 무관하게 항상 계산 가능한 순수 함수라 부작용 없음). title_caption
    # 블록에서는 이 값을 재계산하지 않고 그대로 재사용한다.
    sub_zone = subtitle_zone_y(lay, sub_pos=sub_pos, sub_size=sub_size)
    # 상/하단 예약 스택 전체(진행바/캡션 묶음 + 디스크)를 프레임 중앙으로 옮기는
    # 이동량 — disc_stack_layout() 이 top_reserved/bottom_reserved 가 하나라도
    # True 일 때만 0 이 아닌 값으로 채운다(아래 disc_active 분기 내부). disc_active
    # 가 False 이거나 예약이 전혀 없으면(pos="auto"/캡션 꺼짐) 0 으로 남아, 뒤쪽의
    # 진행바/캡션 draw 호출부가 그 값을 그대로 더해도(top) / H 대신 H-shift 를
    # 넘겨도(bottom) 완전히 no-op — 이 두 호출부는 disc_active 여부와 무관하게
    # 항상 실행되므로 여기서 미리 0 으로 초기화해 둬야 한다.
    stack_shift = 0
    if disc_active:
        D = disc_diameter(lay)
        base_cy = int(H * 0.30) if H > W else int(H * 0.36)  # 세로형은 조금 위
        cy = base_cy

        # 상/하단 레이아웃 재배치 + 세로 오버플로 방지 축소 (신규).
        # --title-caption-pos 가 "top"/"bottom" 으로 명시되고 실제로 캡션 텍스트가
        # 있을 때만 disc_avail_zone() 이 진행바+캡션 예약 영역(양쪽 변 독립,
        # disc_vertical_reservation() 참고)을 반영해 [avail_top, avail_bottom] 을
        # 좁혀 돌려준다(top_reserved/bottom_reserved 로 어느 변이 실제로 예약됐는지
        # 알려준다). pos="auto" 이거나 캡션이 꺼져 있으면(둘 다 False) cy 는 절대
        # 건드리지 않고 위 base_cy 를 그대로 쓴다 — 이 경로는 기존 동작과 100%
        # 동일해야 하는 회귀 방지 경계다.
        # D 축소는 예약 여부와 무관하게 항상 적용한다 — 예약이 전혀 없어도
        # avail_top/avail_bottom 은 순수 프레임 마진(15*scale)을 반영하므로, 캡션/
        # 진행바가 전혀 없는 기본 렌더에서도 lp_vinyl/text_ring/square_spin 조합이
        # 프레임 세로를 벗어나던 기존 버그(예약 전무 -> 축소 전무)가 여기서 함께
        # 고쳐진다. 앵커 계산(아래)이 축소된 D 를 써야 하므로 축소를 cy 계산보다
        # 먼저 한다.
        cap_has_text = bool(cap_title or cap_artist)
        avail_top, avail_bottom, top_reserved, bottom_reserved = disc_avail_zone(
            H, W, scale, title_caption, title_caption_pos, cap_has_text,
            progress_bar, progress_bar_pos, duration)

        # 커버 크기/위치는 테마와 무관하게 항상 "classic"(=D 그대로, 확장 없음) 기준
        # 하나로만 정한다 — disc_theme_max_extent(D, disc_theme) 로 활성 테마 값을
        # 넣으면 테마마다(특히 text_ring TEXT_RING_SCALE=1.15, square_spin
        # sqrt(2)≈1.414) 이 D 자체가 서로 다르게 축소돼, 같은 예약 영역에서도
        # 테마를 바꾸면 앨범 커버 "크기"와 "중심(cy)"까지 달라지는 버그가 있었다
        # (제품 오너 피드백: 테마 바꾸면 커버 크기/캡션 위치가 들쭉날쭉). 링/회전
        # 캔버스 등 테마별 장식(RD/D_lp/VD/off_x)은 여전히 이 공용 D 에 각자의
        # 배율(TEXT_RING_SCALE/sqrt(2)/LP_VINYL_* 등, 아래 각 분기)을 곱해 자기
        # 몫만큼 화면 밖으로 더 튀어나올 수 있다 — 그건 의도된 장식이지 "커버
        # 크기"가 아니므로 여기서 막지 않는다(제품 오너: 타이트한 예약 상황에서
        # 장식이 예약 마진을 살짝 넘는 건 허용, 프레임 자체를 벗어나지만 않으면
        # 됨 — 실측 결과 disc_diameter()/TEXT_RING_SCALE/sqrt(2) 값 범위에서는
        # 프레임 자체를 넘는 경우가 실제로 없음을 확인했다, 아래 테스트 참고).
        shrink = disc_shrink_factor(D, avail_top, avail_bottom, "classic")
        if shrink < 1.0:
            D = int(D * shrink)
            D -= D % 2
            D = max(D, 2)

        # 예약된 변이 하나라도 있으면(top 단독/bottom 단독/양쪽 다) 그 변(들)의
        # 진행바/캡션 묶음 + 디스크를 "존재하는 요소만" 하나의 강체 스택으로 보고
        # 프레임 세로 중앙으로 옮긴다(disc_stack_layout() 참고 — 이전엔 단일 변
        # 케이스에서 디스크를 예약 경계에 DISC_RESERVED_GAP 만큼만 앵커하고 남는
        # 여유를 전부 반대쪽에 몰아넣어, 예: title_caption_pos="bottom" 하나만
        # 켜져 있을 때 화면 위쪽에 거대한 빈 공간이 남고 디스크+캡션 조합이
        # 하단에 짓눌려 보이는 버그가 있었다 — sample/screen.png 재현 확인).
        # stack_shift 는 뒤쪽의 실제 진행바/캡션 draw 호출부에도 반드시 똑같이
        # 적용해야 한다(이 예측과 실제 그리기가 어긋나면 디스크만 중앙으로 옮겨지고
        # 캡션/진행바는 여전히 프레임 가장자리에 붙어버린다) — disc_stack_layout()
        # 의 docstring에 두 호출부가 공유해야 하는 정확한 적용 방식이 있다.
        # 예약이 전혀 없으면(pos="auto"/캡션 꺼짐) disc_stack_layout() 이 그 즉시
        # (0, None) 을 돌려주므로 cy 는 절대 안 건드리고 위 base_cy 를 그대로 쓴다
        # — 이 경로는 기존 동작과 100% 동일해야 하는 회귀 방지 경계다.
        if top_reserved or bottom_reserved:
            reserved_top, reserved_bottom = disc_vertical_reservation(
                H, scale, title_caption, title_caption_pos, cap_has_text,
                pb_will_draw, progress_bar_pos, W)
            stack_shift, stack_cy = disc_stack_layout(
                H, scale, reserved_top, reserved_bottom,
                top_reserved, bottom_reserved, D, sub_zone=sub_zone)
            if stack_cy is not None:
                cy = stack_cy
        # else: 예약 없음(또는 예외적으로 겹쳐 여유가 없는 상황) -> base_cy 그대로.

        # 배경 헤일로: 디스크 뒤에서 은은한 컬러 글로우가 음악(RMS)에 반응해 반짝임.
        # geq 알파 낙차로 소프트 엣지 원을 만들고(추가 -i 입력 불필요, 합성 소스),
        # bg_pulse 와 동일한 RMS 엔벨로프 -> sendcmd -> eq brightness 패턴을 재사용한다.
        if disc_bg_style == "radial":
            HD = int(D * 1.8)
            HD -= HD % 2
            hc = (HD - 1) / 2
            hr = HD / 2
            accent = norm_hex((viz_colors or [None])[0], DEFAULT_VIZ_COLORS[0])
            ar, ag, ab = int(accent[0:2], 16), int(accent[2:4], 16), int(accent[4:6], 16)
            a_expr = f"200*clip(1-hypot(X-{hc:.1f},Y-{hc:.1f})/{hr:.1f},0,1.0)"
            parts.append(
                f"color=c=black:s={HD}x{HD}:r={FPS},format=gbrap,"
                f"geq=r={ar}:g={ag}:b={ab}:a='{a_expr}'[haloraw]")
            halo_label = "[haloraw]"
            env = audio_rms_envelope(audio)
            if env:
                vals = sorted(d for _, d in env)
                base_lvl = vals[len(vals) // 2]
                off = clip_start or 0.0
                lines = []
                for t, d in env:
                    ot = t - off
                    if ot < 0 or (duration and ot > duration):
                        continue
                    b = max(-0.10, min(0.30, (d - base_lvl) * 0.035))
                    lines.append(f"{ot:.2f} eq brightness {b:.3f};")
                if lines:
                    write_textfile("\n".join(lines),
                                   os.path.join(work_dir, "_halo_pulse.cmd"))
                    parts.append(f"{halo_label}sendcmd=f=_halo_pulse.cmd,"
                                 f"eq=brightness=0:eval=frame[halop]")
                    halo_label = "[halop]"
            parts.append(
                f"{cur}{halo_label}overlay=(W-{HD})/2:{cy - HD // 2}[vhalo]")
            cur = "[vhalo]"

        if disc_theme in ("classic", "square_spin"):
            # ---- classic/square_spin: 앨범아트가 그대로(원형 마스킹 또는 정사각)
            #      회전. square_spin 은 회전한 정사각형의 대각선까지 담아야 모서리가
            #      잘리지 않으므로 회전 캔버스를 D*sqrt(2) 로 키운다(안 그러면 45도
            #      회전 시 모서리가 D×D 캔버스에 잘려 팔각형처럼 보임). classic 은
            #      원형이라 회전에 불변 — 캔버스가 그대로 D 여야 기존 동작과 100%
            #      동일하다(하위 호환 필수) ----
            #      add_square_shadow() 는 여기(classic/square_spin) 에는 일부러
            #      안 붙인다. classic 은 make_disc_png 의 흰 링 테두리+소프트 알파
            #      낙차가 이미 배경과의 분리 역할을 한다(렌더 확인:
            #      f4_classic.png, 별도 그림자 없이도 배경과 뚜렷이 분리됨).
            #      square_spin 은 실제로 임의 각도까지 계속 회전하는 정사각형이라
            #      (렌더 확인: f9_ss_a/b.png, 마름모 형태로 자유 회전) 축 정렬
            #      정사각 그림자를 그대로 붙이면 45도 부근에서 그림자 상자
            #      모서리가 회전한 커버의 대각선 밖으로 삐져나와 어긋나 보인다 —
            #      제대로 하려면 그림자도 같은 rotate_expr 로 동기 회전시켜야
            #      하는데, 이는 이번 네 가지 폴리시 항목(표시부만 다룸) 범위를
            #      넘는 별도 작업이라 이번 패치에서는 다루지 않는다.
            disc_idx = audio_idx + 1 + (1 if logo else 0)
            if disc_theme == "square_spin":
                RD = int(math.ceil(D * math.sqrt(2)))
                RD += RD % 2  # 짝수로 (yuv420p/overlay 위치 계산 안전)
            else:
                RD = D
            rotate_expr = f"rotate=2*PI*t/16:ow={RD}:oh={RD}:c=black@0"
            if rotate_eval_flag():
                rotate_expr += ":eval=frame"
            parts.append(
                f"[{disc_idx}:v]format=rgba,{rotate_expr},fps={FPS}[disc]")
            parts.append(f"{cur}[disc]overlay={(W - RD) // 2}:{cy - RD // 2}[vdisc]")
            cur = "[vdisc]"
        elif disc_theme == "lp_vinyl" and vinyl_png and cover_png:
            # ---- lp_vinyl: 회전하는 비닐(LP_VINYL_SCALE 배) 뒤에 정적 정사각
            #      커버를 classic 과 동일한 앵커에 겹친다. 디자인 레퍼런스처럼
            #      한쪽으로 크게 삐져나오는 비대칭 구도(LP_VINYL_OFFSET, 기본 오른쪽 —
            #      --disc-lp-side left 로 반대쪽도 선택 가능) ----
            #      D_lp = D * LP_VINYL_SIZE_SCALE(현재 1.0 — 커버 크기를 다른 세
            #      테마와 통일하기 위해 확대를 걷어냄, 위 상수 정의부 주석 참고).
            #      곱셈 자체는 남겨둔다: main() 프리패스가 cover_png/vinyl_png 를
            #      정확히 이 D_lp 크기로 구웠으므로 오버레이 좌표도 전부 D_lp
            #      기준이어야 한다(D 를 쓰면 실제 PNG 크기와 어긋남) ----
            D_lp = int(D * LP_VINYL_SIZE_SCALE)
            D_lp -= D_lp % 2
            base_idx = audio_idx + 1 + (1 if logo else 0)   # vinyl_png 입력
            cover_idx = base_idx + 1                        # cover_png 입력
            VD = int(D_lp * LP_VINYL_SCALE)
            VD -= VD % 2
            # 오프셋 크기(항상 양수) + 방향 부호. LP_VINYL_OFFSET 비율은 레퍼런스
            # 실측 근거가 있어 그대로 두고(주석 참고), 제품 오너가 "조금 더
            # 삐져나오게" 요청한 만큼만 스케일 보정된 고정 픽셀을 더한다 — 이 합산값
            # (off_x) 이 부호까지 포함해 아래 vx/바운딩박스 계산에 그대로 흘러들어가야
            # 두 계산이 어긋나지 않는다.
            off_mag = int(D_lp * LP_VINYL_OFFSET) + int(round(LP_VINYL_OFFSET_NUDGE_PX * scale))
            off_x = off_mag if disc_lp_side != "left" else -off_mag
            rotate_expr = f"rotate=2*PI*t/16:ow={VD}:oh={VD}:c=black@0"
            if rotate_eval_flag():
                rotate_expr += ":eval=frame"
            parts.append(
                f"[{base_idx}:v]format=rgba,{rotate_expr},fps={FPS}[vinylrot]")
            # 커버+비닐 "조합"의 바운딩박스를 화면 중앙에 맞춘다(제품 오너 피드백:
            # 예전엔 커버만 W/2 에 중심을 두고 비닐이 거기서 더 튀어나가 조합 전체가
            # 한쪽으로 쏠려 보였다 — sample/playscreen.png). lp_vinyl_cover_center_x()
            # 가 커버/비닐 각 변 좌표를 min/max 로 비교해 바운딩박스를 구하므로,
            # --disc-lp-side 로 off_x 부호가 바뀌어도(왼쪽/오른쪽 어느 쪽이 실제로
            # 더 튀어나오는지 하드코딩하지 않고) 항상 정확히 중앙정렬된다.
            cover_cx = lp_vinyl_cover_center_x(W, D_lp, VD, off_x)
            vx = cover_cx + off_x - VD // 2
            vy = cy - VD // 2
            parts.append(f"{cur}[vinylrot]overlay={vx}:{vy}[vvinyl]")
            cur = "[vvinyl]"
            cov_x, cov_y = cover_cx - D_lp // 2, cy - D_lp // 2
            cur = add_square_shadow(parts, cur, D_lp, cov_x, cov_y, FPS, "lp")
            parts.append(f"[{cover_idx}:v]format=rgba[coverfg]")
            parts.append(f"{cur}[coverfg]overlay={cov_x}:{cov_y}[vdisc]")
            cur = "[vdisc]"
        elif disc_theme == "text_ring" and ring_png and cover_png:
            # ---- text_ring: 회전하는 텍스트 링(TEXT_RING_SCALE 배) + 정적 커버.
            #      디자인 레퍼런스처럼 커버 중심에서 밀어(TEXT_RING_OFFSET, 기본
            #      왼쪽 — --disc-ring-side right 로 반대쪽도 선택 가능) 대부분
            #      커버 뒤에 가려지고 한쪽에 초승달 모양으로만 노출되게 ----
            #      lp_vinyl(round 3) 과 달리 커버 위치(cover_cx)는 항상 W/2 고정 —
            #      링만 움직이고 커버는 안 움직이므로(아래), --disc-ring-side 는
            #      off_x 부호만 뒤집으면 되고 lp_vinyl_cover_center_x() 같은 별도
            #      바운딩박스 재중앙 계산은 필요 없다(렌더로 직접 확인, round 5
            #      보고 참고).
            base_idx = audio_idx + 1 + (1 if logo else 0)   # ring_png 입력
            cover_idx = base_idx + 1                        # cover_png 입력
            RD = int(D * TEXT_RING_SCALE)
            RD -= RD % 2
            off_mag = int(D * TEXT_RING_OFFSET)  # 커버 뒤에서 밀어 초승달 노출(크기)
            off_x = off_mag if disc_ring_side == "right" else -off_mag
            rotate_expr = f"rotate=2*PI*t/16:ow={RD}:oh={RD}:c=black@0"
            if rotate_eval_flag():
                rotate_expr += ":eval=frame"
            parts.append(
                f"[{base_idx}:v]format=rgba,{rotate_expr},fps={FPS}[ringrot]")
            cover_cx = (W - D) // 2 + D // 2
            rx = cover_cx + off_x - RD // 2
            ry = cy - RD // 2
            parts.append(f"{cur}[ringrot]overlay={rx}:{ry}[vring]")
            cur = "[vring]"
            cov_x, cov_y = (W - D) // 2, cy - D // 2
            cur = add_square_shadow(parts, cur, D, cov_x, cov_y, FPS, "tr")
            parts.append(f"[{cover_idx}:v]format=rgba[coverfg]")
            parts.append(f"{cur}[coverfg]overlay={cov_x}:{cov_y}[vdisc]")
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

    # ---- 상시 노출 제목/아티스트 캡션 (--title-caption, 전체 재생시간 고정) ----
    # --title/--artist 는 썸네일 등 다른 용도로도 쓰이므로, 이 오버레이는 명시적
    # opt-in(--title-caption)일 때만 그린다 — 자동으로 켜지지 않는다.
    if title_caption and (cap_title or cap_artist):
        # sub_zone 은 위(disc_active 분기 이전)에서 이미 계산해 뒀다 — disc_stack_layout()
        # 의 자막 충돌 클램프와 여기 title_caption_geometry() 의 pos="auto" 회피 로직이
        # 항상 같은 값을 봐야 하므로 재계산하지 않고 재사용한다.
        # stack_shift 적용(disc_stack_layout() 의 사용법 docstring 참고): pos="top"
        # 이면 H 는 그대로 두고 나중에 ttl_y 에 더하고, pos="bottom" 이면 H 대신
        # H-stack_shift 를 넘긴다(그 분기 내부 공식이 전부 "H - 상수" 형태라 이렇게
        # 하면 함수를 안 건드리고도 정확히 같은 양만큼 위로 밀린다). disc_active 가
        # False 이거나 예약이 없으면(pos="auto") stack_shift==0 이라 완전히 no-op —
        # 기존 동작과 100% 동일하게 유지된다.
        cap_H = H - stack_shift if title_caption_pos == "bottom" else H
        ttl_fs, art_fs, ttl_y, art_gap = title_caption_geometry(
            disc_active, D if disc_active else 0, cy if disc_active else 0,
            cap_H, scale, pos=title_caption_pos, sub_zone=sub_zone,
            W=W, progress_bar=pb_will_draw, progress_bar_pos=progress_bar_pos)
        if title_caption_pos == "top":
            ttl_y += stack_shift
        cap_y = ttl_y
        if cap_title:
            write_textfile(cap_title, os.path.join(work_dir, "_cap_ttl.txt"))
            parts.append(
                f"{cur}drawtext={draw_font_spec()}:textfile=_cap_ttl.txt:"
                f"fontcolor=white:fontsize={ttl_fs}:x=(w-tw)/2:y={cap_y}:"
                "shadowcolor=black@0.7:shadowx=2:shadowy=2[vcapt]")
            cur = "[vcapt]"
            cap_y = ttl_y + art_gap
        if cap_artist:
            write_textfile(cap_artist, os.path.join(work_dir, "_cap_art.txt"))
            parts.append(
                f"{cur}drawtext={draw_font_spec()}:textfile=_cap_art.txt:"
                f"fontcolor=white@0.85:fontsize={art_fs}:x=(w-tw)/2:y={cap_y}:"
                "shadowcolor=black@0.6:shadowx=2:shadowy=2[vcapa]")
            cur = "[vcapa]"

    # ---- 간주(가사 없는 긴 구간)에 ♪ 표시 ----
    if gaps:
        enable = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e in gaps)
        parts.append(
            f"{cur}drawtext={symbol_font_spec()}:text='♪':fontcolor=white@0.45:"
            f"fontsize={int(round(120*scale))}:x=(w-tw)/2:y=(h-th)/2:"
            f"enable='{enable}'[vnote]")
        cur = "[vnote]"

    # ---- 곡 진행바: 둥근 알약 트랙 + 진행 필 (파형 색과 통일, 상/하단 선택) ----
    # 트랙(고정, 은은한 흰색 알약)을 먼저 깔고, 그 위에 파형 색 필을 T(초 단위
    # 타임스탬프, geq 내장 변수)로 매 프레임 새로 그려 왼쪽부터 채운다 — 필의
    # 오른쪽 반원 끝이 항상 '지금 재생 위치'를 가리키는 손잡이처럼 보인다.
    # (오버레이 x 를 시간에 따라 슬라이드시키는 옛 트릭은 트랙에 여백을 두면
    #  0% 지점에서 필 몸통 일부가 여백 안쪽으로 새어 보이는 문제가 있어 안 씀.)
    if progress_bar and duration:
        # stack_shift 적용(disc_stack_layout() 사용법 참고, 위 title_caption 호출부와
        # 동일한 방식) — progress_bar_pos=="top" 이면 나중에 pb_y 에 더하고,
        # "bottom" 이면 H 대신 H-stack_shift 를 넘긴다. title_caption 이 꺼져
        # 있거나(gate 자체가 title_caption 활성을 요구) pos="auto" 면 stack_shift
        # 는 항상 0 이라 완전히 no-op.
        pb_H = H - stack_shift if progress_bar_pos == "bottom" else H
        margin_x, bar_w, bar_h, pb_y = progress_bar_geometry(
            W, pb_H, scale, progress_bar_pos)
        if progress_bar_pos == "top":
            pb_y += stack_shift
        # --progress-bar-color 로 명시하면 그 색을 그대로 쓰고(파형 색과 독립),
        # 안 주면(None/빈값/잘못된 hex) 기존처럼 viz_colors[0] 유도값으로 폴백한다
        # — 순수 additive 변경, progress_bar_color 를 안 주는 기존 호출부는 완전히
        # 동일한 동작을 유지한다.
        accent = norm_hex(progress_bar_color, None) or norm_hex(
            (viz_colors or [None])[0], DEFAULT_VIZ_COLORS[0])
        ar, ag, ab = int(accent[0:2], 16), int(accent[2:4], 16), int(accent[4:6], 16)
        fill_expr = f"{bar_w}*clip(T/{duration:.3f},0,1)"
        track_a = pill_alpha_expr(bar_w, bar_h, 0.30)
        fill_a = pill_alpha_expr(bar_w, bar_h, 0.92, fill_expr=fill_expr)
        parts.append(
            f"color=c=white:s={bar_w}x{bar_h}:r={FPS},format=gbrap,"
            f"geq=r=255:g=255:b=255:a='{track_a}'[pbtrack]")
        parts.append(f"{cur}[pbtrack]overlay={margin_x}:{pb_y}[vpbt]")
        cur = "[vpbt]"
        parts.append(
            f"color=c=0x{accent}:s={bar_w}x{bar_h}:r={FPS},format=gbrap,"
            f"geq=r={ar}:g={ag}:b={ab}:a='{fill_a}'[pbfill]")
        parts.append(f"{cur}[pbfill]overlay={margin_x}:{pb_y}[vpb]")
        cur = "[vpb]"

        # ---- 진행 위치 손잡이(핸들): 필 경계에 얹히는 원형 점 ----
        # 레퍼런스(sample/playlist_sample1.png)를 PIL 로 실측: 트랙 자체는 세로로
        # 9px(y 124~132)인데, 재생 위치의 원형 점은 같은 x 열에서 세로로 18px
        # (y 119~137)까지 튀어나와 있다 — 트랙 높이 대비 지름 비율 ≈2.0, 색은
        # 트랙과 같은 흰색(채움 색인 accent 가 아님). pill_alpha_expr 을 fill_expr
        # 없이 정사각 캔버스(handle_d x handle_d)에 쓰면 hypot 클램프가 자동으로
        # w==h 인 원(반지름=h/2)이 되므로 새 헬퍼 없이 재사용 가능.
        # 위치는 필과 같은 T(=재생 경과초)/duration 비율을 오버레이 x 표현식에
        # 그대로 옮겨(overlay 는 소문자 t, eval=frame 필요) 매 프레임 슬라이드
        # 시킨다 — 필 자체를 overlay-x 슬라이드로 그리지 않는 이유(위 주석, 여백
        # 누수 문제)는 작은 별도 원 에셋인 핸들에는 해당하지 않는다.
        handle_d = max(bar_h + 2, int(round(bar_h * 2.0)))
        handle_a = pill_alpha_expr(handle_d, handle_d, 1.0)
        handle_y = pb_y + bar_h // 2 - handle_d // 2
        handle_x_expr = f"{margin_x}+{bar_w}*clip(t/{duration:.3f},0,1)-{handle_d}/2"
        parts.append(
            f"color=c=white:s={handle_d}x{handle_d}:r={FPS},format=gbrap,"
            f"geq=r=255:g=255:b=255:a='{handle_a}'[pbhandle]")
        parts.append(
            f"{cur}[pbhandle]overlay=x='{handle_x_expr}':y={handle_y}:"
            f"eval=frame[vpbh]")
        cur = "[vpbh]"

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

    # 입력 구성: [배경 이미지들...] [오디오] [로고] [레코드 모드: disc_png 또는 (vinyl/ring, cover)]
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
    elif vinyl_png and cover_png:
        cmd += ["-loop", "1", "-i", os.path.abspath(vinyl_png)]
        cmd += ["-loop", "1", "-i", os.path.abspath(cover_png)]
    elif ring_png and cover_png:
        cmd += ["-loop", "1", "-i", os.path.abspath(ring_png)]
        cmd += ["-loop", "1", "-i", os.path.abspath(cover_png)]

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
    ap.add_argument("--disc-lp-art",
                     help="lp_vinyl 테마 전용: LP판 라벨에 쓸 별도 이미지 "
                          "(기본: 지정 안 하면 --disc-art 와 같은 이미지를 그대로 사용)")
    ap.add_argument("--disc-lp-side", choices=["left", "right"], default="right",
                     help="lp_vinyl 테마 전용: 비닐이 커버 뒤로 삐져나오는 방향 "
                          "(기본 right=오른쪽, left=왼쪽으로 미러링)")
    ap.add_argument("--disc-bg-style", choices=["off", "glow", "radial"], default="off",
                    help="레코드 모드 배경: glow=앨범아트 블러+글로우로 배경 전체 대체, "
                         "radial=디스크 뒤 컬러 헤일로가 음악(RMS)에 반응해 반짝임")
    ap.add_argument("--disc-theme",
                    choices=["classic", "lp_vinyl", "text_ring", "square_spin"],
                    default="classic",
                    help="레코드 모드 테마: classic=원형 앨범아트가 그대로 회전(기본), "
                         "lp_vinyl=정사각 커버 뒤로 검은 바이닐 LP가 살짝 비치며 회전, "
                         "text_ring=커버 둘레를 도는 회전 텍스트 링, "
                         "square_spin=정사각 앨범아트가 마스킹 없이 그대로 회전")
    ap.add_argument("--disc-ring-text", default=None,
                    help="text_ring 테마 전용: 원형으로 도는 문구 "
                         "(기본: 제목/아티스트 또는 자동 문구, --disc-theme text_ring 일 때만 사용)")
    ap.add_argument("--disc-ring-side", choices=["left", "right"], default="left",
                     help="text_ring 테마 전용: 텍스트 링이 커버 뒤로 삐져나오는 방향 "
                          "(기본 left=왼쪽, right=오른쪽으로 미러링). --disc-lp-side 와는 "
                          "별개의 독립된 옵션(테마도 다름)")
    ap.add_argument("--progress-bar", action="store_true",
                    help="곡 진행바(둥근 알약 트랙 + 진행 필, 파형 색과 통일). "
                         "위치는 --progress-bar-pos 로 선택 (기본 하단)")
    ap.add_argument("--progress-bar-pos", choices=["top", "bottom"], default="bottom",
                    help="진행바 위치: bottom=하단(기본, 기존 동작), top=상단")
    ap.add_argument("--progress-bar-color", default=None, metavar="RRGGBB",
                    help="진행바 채움 색(hex). 지정 안 하면 --viz-color[0] "
                         "(파형 색)을 그대로 따라간다(기본, 기존 동작)")
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
    ap.add_argument("--title-caption", action="store_true",
                    help="곡 제목/아티스트를 전체 재생시간 내내 고정 노출 "
                         "(--title/--artist 가 있어도 자동으로 켜지지 않음, 명시적 opt-in). "
                         "레코드 모드면 디스크 바로 아래, 아니면 화면 상단")
    ap.add_argument("--title-caption-pos", choices=["auto", "top", "bottom"], default="auto",
                    help="--title-caption 위치: auto=레코드 모드면 디스크 바로 아래·"
                         "아니면 화면 상단(기본), top=레코드 모드여도 항상 화면 상단, "
                         "bottom=항상 화면 하단(진행바가 --progress-bar-pos bottom 이면 "
                         "같은 묶음으로 타이트하게 붙는다). top/bottom 은 디스크를 남은 "
                         "세로 공간의 중앙으로 재배치하고 필요시 축소한다")
    ap.add_argument("--interlude-note", action="store_true",
                    help="가사 없는 긴 구간(간주)에 ♪ 표시")
    ap.add_argument("--keep-ass", action="store_true")
    ap.add_argument("--keep-meta-lines", action="store_true",
                    help="SUNO 프롬프트 형식 섹션 태그/연출 지시문 자동 제외를 끄고 모든 줄을 가사로 취급")
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
            if not args.keep_meta_lines:
                lines, dropped = filter_lyric_lines(lines, drop_stage_directions=False)
                if dropped:
                    print(f"[info] SUNO 프롬프트 형식 줄 {len(dropped)}개 자동 제외 (섹션 태그/연출 지시문)")
            cues = align_with_stable_ts(args.audio, "\n".join(lines), args.align_model,
                                        language=args.align_lang)
            print(f"[info] 강제정렬 {len(cues)}줄")
        elif ext == ".lrc":
            cues = lrc_to_cues(parse_lrc(args.lyrics), full_dur)
            print(f"[info] LRC {len(cues)}줄 (정확한 싱크)")
        else:
            lines = read_txt_lines(args.lyrics)
            if not args.keep_meta_lines:
                lines, dropped = filter_lyric_lines(lines, drop_stage_directions=True)
                if dropped:
                    print(f"[info] SUNO 프롬프트 형식 줄 {len(dropped)}개 자동 제외 (섹션 태그/연출 지시문)")
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

    # 레코드 모드: 테마별 프리패스 (classic=원형 마스킹, lp_vinyl/text_ring=정사각 커버 +
    # 각각 비닐/텍스트링 PNG)
    disc_png = None
    cover_png = None
    vinyl_png = None
    ring_png = None
    if args.disc:
        art = args.disc_art or (args.bg[0] if args.bg else None)
        D = disc_diameter(lay)
        # 세로 오버플로 방지 축소: render() 의 disc_active 분기와 반드시 같은
        # disc_avail_zone()/disc_shrink_factor() 를 호출해야 한다 — 이 프리패스가
        # 굽는 PNG 픽셀 크기(D/D_lp/VD/RD)와 render() 의 오버레이 배치 크기가
        # 어긋나면(따로 계산 시 흔한 함정) 크기가 안 맞는 결과가 나온다
        # (LP_VINYL_SIZE_SCALE 프리패스/오버레이 공식 불일치와 동일한 종류의 함정 —
        # 위 disc_shrink_factor() 주석 참고). --title-caption-pos/--progress-bar-pos
        # 등 CLI 인자를 그대로 넘겨 render() 호출 시 쓰일 값과 동일하게 맞춘다.
        # theme 인자는 항상 "classic" 고정 — 커버 크기 기준을 테마와 무관하게
        # 하나로 통일하기 위함(render() 의 동일한 disc_shrink_factor 호출부 주석
        # 참고). args.disc_theme 을 넘기면 테마마다 이 D 자체가 달라져 커버 크기가
        # 테마별로 들쭉날쭉해지는 버그가 있었다.
        avail_top, avail_bottom, _, _ = disc_avail_zone(
            lay["H"], lay["W"], scale, args.title_caption, args.title_caption_pos,
            bool(args.title or args.artist), args.progress_bar, args.progress_bar_pos,
            render_dur)
        shrink = disc_shrink_factor(D, avail_top, avail_bottom, "classic")
        if shrink < 1.0:
            D = int(D * shrink)
            D -= D % 2
            D = max(D, 2)
        accent = norm_hex((args.viz_color or [None])[0], DEFAULT_VIZ_COLORS[0])
        if not art or not os.path.exists(art):
            # 앨범아트가 전혀 없어도 레코드 모드가 그대로 동작하도록 기본 커버로
            # 대체(그라데이션+♪). 사용자가 나중에 실제 앨범아트를 넣으면 이 대체는
            # 자동으로 안 쓰인다(art 가 있으면 위 조건에서 걸리지 않음).
            art = os.path.join(out_dir, "_default_cover_src.png")
            make_default_cover_png(art, D, accent)
            print("[info] 레코드 모드: 앨범아트가 없어 기본 커버(그라데이션+♪)로 대체")
        if args.disc_theme == "lp_vinyl":
            cover_png = os.path.join(out_dir, "_cover.png")
            vinyl_png = os.path.join(out_dir, "_vinyl.png")
            # D_lp: render() 의 lp_vinyl 오버레이 분기와 반드시 같은 공식으로
            # 계산해야 한다(LP_VINYL_SIZE_SCALE 참고) — 어긋나면 크기가 안 맞는다.
            D_lp = int(D * LP_VINYL_SIZE_SCALE)
            D_lp -= D_lp % 2
            make_square_png(art, cover_png, D_lp)
            VD = int(D_lp * LP_VINYL_SCALE)
            # LP판 라벨 아트는 앨범 커버와 다르게 지정할 수 있다(--disc-lp-art).
            # 지정 안 했거나 파일이 없으면 기존처럼 커버와 같은 art 를 그대로 쓴다
            # (하위 호환 — 기존 사용자는 아무것도 안 바꿔도 이전과 동일하게 동작).
            lp_art = art
            if args.disc_lp_art and os.path.exists(args.disc_lp_art):
                lp_art = args.disc_lp_art
            make_vinyl_png(vinyl_png, VD, accent, art_src=lp_art)
        elif args.disc_theme == "text_ring":
            cover_png = os.path.join(out_dir, "_cover.png")
            ring_png = os.path.join(out_dir, "_ring.png")
            make_square_png(art, cover_png, D)
            RD = int(D * TEXT_RING_SCALE)
            ring_text = args.disc_ring_text or default_ring_text(args.title, args.artist)
            font_path = bundled_font_file(SUB_FONT) or DRAW_FONTFILE
            make_ring_text_png(ring_png, RD, ring_text, font_path)
        elif args.disc_theme == "square_spin":
            # square_spin: classic 과 구조가 동일(회전할 PNG 1장을 disc_png
            # 슬롯에 넣고 render() 의 classic 분기를 그대로 재사용) —
            # 원형 마스킹(make_disc_png) 대신 정사각 크롭만 다르다.
            disc_png = os.path.join(out_dir, "_disc.png")
            make_square_png(art, disc_png, D)
        else:
            disc_png = os.path.join(out_dir, "_disc.png")
            make_disc_png(art, disc_png, D)

    # 별도 배경 이미지가 없으면(레코드 모드의 앨범아트만 있는 경우) build_bg() 는
    # bg_list 가 비어 있어 disc_bg_style 을 무시하고 그라데이션으로 빠진다 —
    # 레퍼런스(sample/playlist_sample1.png)처럼 앨범아트 자체를 블러 배경으로
    # 쓰고 싶을 땐 그 art 이미지를 bg_list 대신 넣어준다.
    bg_for_render = args.bg
    if args.disc and not args.bg and args.disc_bg_style == "glow":
        bg_for_render = [art]

    # 스크림: 명시 지정(--scrim/--no-scrim) 없으면 배경 이미지/영상이 있을 때
    # 자동 on(레코드 모드가 앨범아트를 배경으로 대신 쓰는 경우도 포함 —
    # bg_for_render 기준) — 단, disc_bg_style=="glow" 는 예외다. glow 배경은
    # 이미 앨범아트 자체를 블러+채도업해서 배경 전체를 채우는 처리라, 그 위에
    # 하단 스크림(화면 하단 38%, ≈55% 검게)까지 또 얹으면 하단이 짙은 검은
    # 띠로 뭉개져 보인다(제품 오너 피드백: "배경 하단 부분이 검은색이 짙어").
    # 자막/캡션/진행바는 이미 각자 자체 outline+shadow(write_ass() 의
    # BorderStyle=1/Outline=3/Shadow=1, drawtext 의 shadowcolor)로 가독성을
    # 확보하므로 스크림이 없어도 읽는 데 문제없다 — glow 모드에서는 자동 기본값을
    # off 로 낮춘다. off/radial(레코드 모드 꺼짐 또는 헤일로)은 이 버그 리포트
    # 대상이 아니므로 기존 자동 on 기본값을 그대로 유지한다. --scrim/--no-scrim
    # 를 명시하면(glow 여부와 무관하게) 항상 그 값이 우선한다(기존 "명시가 계산된
    # 기본값을 이긴다" 패턴 그대로).
    scrim_auto_on = bool(bg_for_render or args.video_bg) and args.disc_bg_style != "glow"
    scrim = args.scrim if args.scrim is not None else scrim_auto_on

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
           bg_list=bg_for_render, viz=args.viz, bg_color=args.bg_color,
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
           progress_bar_pos=args.progress_bar_pos,
           progress_bar_color=args.progress_bar_color,
           sparkle=args.sparkle, outro_cta=args.outro_cta,
           outro_cta_text=args.outro_cta_text,
           disc_bg_style=args.disc_bg_style, disc_theme=args.disc_theme,
           disc_ring_text=args.disc_ring_text,
           cover_png=cover_png, vinyl_png=vinyl_png, ring_png=ring_png,
           title_caption=args.title_caption, cap_title=args.title or "",
           cap_artist=args.artist or "", title_caption_pos=args.title_caption_pos,
           sub_pos=args.sub_pos, sub_size=args.sub_size,
           disc_lp_side=args.disc_lp_side, disc_ring_side=args.disc_ring_side)

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
                    "_outro_cta.txt", "_halo_pulse.cmd",
                    "_cover.png", "_vinyl.png", "_ring.png",
                    "_cap_ttl.txt", "_cap_art.txt"):
            try:
                os.remove(os.path.join(out_dir, tmp))
            except OSError:
                pass

if __name__ == "__main__":
    main()
