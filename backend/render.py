"""make_mv.py(렌더 엔진)를 서브프로세스로 감싸는 래퍼."""
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
    if opts.get("normalize"):
        cmd += ["--normalize"]
    if opts.get("fade_in"):
        cmd += ["--fade-in", str(opts["fade_in"])]
    if opts.get("fade_out"):
        cmd += ["--fade-out", str(opts["fade_out"])]
    if opts.get("vignette"):
        cmd += ["--vignette"]
    if opts.get("film_grain"):
        cmd += ["--film-grain"]

    return cmd, out


def run_render(job_dir, audio, lyrics, bg_list, opts, on_progress=None):
    """렌더 실행. 반환: (returncode, log, out_path).

    make_mv.py 가 출력하는 'MV_PROGRESS <pct>' 라인은 진행률 콜백으로 보내고
    로그에선 제외한다."""
    cmd, out = build_command(job_dir, audio, lyrics, bg_list, opts)
    proc = subprocess.Popen(
        cmd, cwd=job_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
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
