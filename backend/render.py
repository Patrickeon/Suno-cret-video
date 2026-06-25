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
    if bg_list:
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

    return cmd, out


def run_render(job_dir, audio, lyrics, bg_list, opts):
    """렌더 실행. 반환: (returncode, log, out_path)"""
    cmd, out = build_command(job_dir, audio, lyrics, bg_list, opts)
    proc = subprocess.run(
        cmd, cwd=job_dir, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, log, out
