"""make_mv.py(렌더 엔진)를 서브프로세스로 감싸는 래퍼."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKE_MV = os.path.join(ROOT, "make_mv.py")


def build_command(job_dir, audio, lyrics, bg_list, opts):
    """옵션 dict -> make_mv.py CLI 명령. 반환: (cmd, out_path)"""
    out = os.path.join(job_dir, "out.mp4")
    cmd = [sys.executable, MAKE_MV, "--audio", audio, "--out", out]

    if lyrics:
        cmd += ["--lyrics", lyrics]
    if opts.get("font"):
        cmd += ["--font", str(opts["font"])]
    if opts.get("video_bg"):
        cmd += ["--video-bg", opts["video_bg"]]
    elif bg_list:
        cmd += ["--bg"] + bg_list

    cmd += ["--viz", opts.get("viz", "waves")]

    if opts.get("shorts"):
        cmd += ["--shorts"]
    clip_start = opts.get("clip_start")
    if clip_start:
        cmd += ["--clip-start", str(clip_start),
                "--clip-len", str(opts.get("clip_len", 30))]
    if not opts.get("kenburns", True):
        cmd += ["--no-kenburns"]
    if opts.get("title"):
        cmd += ["--title", opts["title"]]
    if opts.get("artist"):
        cmd += ["--artist", opts["artist"]]
    if opts.get("logo"):
        cmd += ["--logo", opts["logo"]]
    if opts.get("watermark"):
        cmd += ["--watermark", opts["watermark"]]
    if opts.get("align") == "auto":
        cmd += ["--align", "auto"]
    if opts.get("bg_color"):
        cmd += ["--bg-color", str(opts["bg_color"])]
    if opts.get("intro"):
        cmd += ["--intro", str(opts["intro"])]
    if opts.get("outro"):
        cmd += ["--outro", str(opts["outro"])]
    # 유튜브 인코딩 / 오디오 / 분위기
    if str(opts.get("res", "1080")) != "1080":
        cmd += ["--res", str(opts["res"])]
    if int(opts.get("fps", 30) or 30) != 30:
        cmd += ["--fps", str(int(opts["fps"]))]
    if opts.get("master"):
        cmd += ["--master"]
    elif opts.get("normalize"):
        cmd += ["--normalize"]
    if opts.get("karaoke"):
        cmd += ["--karaoke"]
    if opts.get("fade_in"):
        cmd += ["--fade-in", str(opts["fade_in"])]
    if opts.get("fade_out"):
        cmd += ["--fade-out", str(opts["fade_out"])]
    if opts.get("vignette"):
        cmd += ["--vignette"]
    if opts.get("film_grain"):
        cmd += ["--film-grain"]
    if opts.get("bg_pulse"):
        cmd += ["--bg-pulse"]
    # 자막 스타일
    if opts.get("sub_color") and str(opts["sub_color"]).upper() != "FFFFFF":
        cmd += ["--sub-color", str(opts["sub_color"])]
    if opts.get("sub_size") and float(opts["sub_size"]) != 1.0:
        cmd += ["--sub-size", str(opts["sub_size"])]
    if opts.get("sub_pos") and opts["sub_pos"] != "bottom":
        cmd += ["--sub-pos", str(opts["sub_pos"])]
    if opts.get("sub_glow"):
        cmd += ["--sub-glow"]
    if opts.get("intro_card"):
        cmd += ["--intro-card"]
    if opts.get("interlude_note"):
        cmd += ["--interlude-note"]
    if opts.get("preview"):
        cmd += ["--preview-secs", str(int(opts.get("preview_secs", 8)))]

    return cmd, out


def _probe_wh_fps(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,r_frame_rate", "-of", "json", path])
    st = json.loads(out)["streams"][0]
    num, den = (st.get("r_frame_rate") or "30/1").split("/")
    fps = round(float(num) / float(den)) if float(den) else 30
    return st["width"], st["height"], max(1, fps)


def _has_audio(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    return bool(out)


def _duration(path):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", path])
        return float(out.strip())
    except (subprocess.CalledProcessError, ValueError):
        return 3.0


def concat_clips(main, intro=None, outro=None):
    """intro + main + outro 를 main 해상도/fps 에 맞춰 재인코딩 concat.
    오디오 없는 클립은 무음으로 채운다. 성공 시 결과로 main 을 덮어씀."""
    clips = [c for c in (intro, main, outro) if c and os.path.exists(c)]
    if len(clips) < 2:
        return  # 붙일 게 없음
    W, H, fps = _probe_wh_fps(main)
    inputs, parts, vlabels, alabels = [], [], [], []
    for c in clips:
        inputs += ["-i", c]
    ai = len(clips)  # 무음 입력이 붙을 다음 인덱스
    silent_inputs = []
    for i, c in enumerate(clips):
        parts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={fps},format=yuv420p[v{i}]")
        if _has_audio(c):
            parts.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
        else:
            silent_inputs += ["-f", "lavfi", "-t", f"{_duration(c):.3f}",
                              "-i", "anullsrc=r=48000:cl=stereo"]
            parts.append(f"[{ai}:a]anull[a{i}]")
            ai += 1
        vlabels.append(f"[v{i}]")
        alabels.append(f"[a{i}]")
    n = len(clips)
    concat_in = "".join(v + a for v, a in zip(vlabels, alabels))
    parts.append(f"{concat_in}concat=n={n}:v=1:a=1[v][a]")
    tmp = main + ".concat.mp4"
    cmd = (["ffmpeg", "-y"] + inputs + silent_inputs +
           ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
            "-movflags", "+faststart", tmp])
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode == 0 and os.path.exists(tmp):
        os.replace(tmp, main)
    else:
        raise RuntimeError("인트로/아웃트로 병합 실패: " + (proc.stderr or "")[-300:])


def run_render(job_dir, audio, lyrics, bg_list, opts, on_progress=None, on_proc=None):
    """렌더 실행. 반환: (returncode, log, out_path).

    make_mv.py 가 출력하는 'MV_PROGRESS <pct>' 라인은 진행률 콜백으로 보내고
    로그에선 제외한다. on_proc 가 주어지면 Popen 객체를 넘겨 취소(kill)에 쓴다."""
    cmd, out = build_command(job_dir, audio, lyrics, bg_list, opts)
    proc = subprocess.Popen(
        cmd, cwd=job_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    if on_proc:
        on_proc(proc)
    log_lines = []
    for line in proc.stdout:
        if line.startswith("MV_PROGRESS"):
            if on_progress:
                try:
                    on_progress(int(line.split()[1]))
                except (ValueError, IndexError):
                    pass
        else:
            log_lines.append(line)
    proc.wait()
    return proc.returncode, "".join(log_lines), out
