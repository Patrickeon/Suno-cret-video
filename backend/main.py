"""Suno MV Studio — FastAPI 백엔드.

음원/가사/배경 업로드 -> make_mv.py 렌더 -> 비동기 잡 -> 비디오/썸네일 서빙.
프론트(Next.js, :3000)에서 호출.
"""
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import agent
import jobs
import render
import settings

app = FastAPI(title="Suno MV Studio API")

# 허용 출처: 기본은 로컬, 배포 시 ALLOWED_ORIGINS(쉼표구분)로 프론트 URL 지정
_origins = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 렌더는 CPU 무거움 -> 동시 2개로 제한
EXECUTOR = ThreadPoolExecutor(max_workers=2)

# 업로드 제한
MAX_AUDIO_MB = 60
MAX_IMAGE_MB = 15
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
LYRICS_EXTS = {".txt", ".lrc"}


class UploadError(Exception):
    pass


def _check_ext(filename: str, allowed: set, label: str):
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in allowed:
        raise UploadError(f"{label} 형식이 아닙니다: {ext or '(없음)'} (허용: {', '.join(sorted(allowed))})")
    return ext


def _save_upload(up: UploadFile, dest: str, max_mb: int):
    """크기 제한을 지키며 청크 저장. 초과 시 UploadError."""
    limit = max_mb * 1024 * 1024
    total = 0
    with open(dest, "wb") as f:
        while True:
            chunk = up.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                f.close()
                os.remove(dest)
                raise UploadError(f"파일이 너무 큽니다 (최대 {max_mb}MB)")
            f.write(chunk)


@app.on_event("startup")
def _startup():
    jobs.load_all()
    removed = jobs.cleanup()
    if removed:
        print(f"[startup] 오래된 잡 {removed}개 정리")


def _do_render(jid, d, audio, lyrics, bg_paths, opts):
    jobs.update(jid, status="running", opts=opts)
    try:
        code, log, out = render.run_render(d, audio, lyrics, bg_paths, opts)
        log = log[-2000:]  # 잡 응답이 비대해지지 않게 끝부분만 보관
        thumb = os.path.splitext(out)[0] + "_thumb.jpg"
        if code == 0 and os.path.exists(out):
            jobs.update(jid, status="done", log=log,
                        video=True, thumb=os.path.exists(thumb))
        else:
            jobs.update(jid, status="error", log=log,
                        error="렌더 실패 (로그 확인)")
    except Exception as e:  # noqa: BLE001
        jobs.update(jid, status="error", error=str(e))


@app.get("/api/health")
def health():
    return {"ok": True}


class SettingsBody(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    video_provider: str | None = None
    video_api_key: str | None = None


@app.get("/api/settings")
def get_settings():
    return settings.get_public()


@app.post("/api/settings")
def post_settings(body: SettingsBody):
    return settings.update(body.model_dump(exclude_none=True))


@app.post("/api/render")
async def create_render(
    audio: UploadFile = File(...),
    lyrics_file: Optional[UploadFile] = File(None),
    bg: List[UploadFile] = File(default=[]),
    lyrics_text: str = Form(""),
    viz: str = Form("waves"),
    shorts: bool = Form(False),
    clip_start: str = Form(""),
    clip_len: float = Form(30),
    kenburns: bool = Form(True),
    title: str = Form(""),
    artist: str = Form(""),
    watermark: str = Form(""),
    align: str = Form("none"),
):
    # 입력 검증
    try:
        _check_ext(audio.filename, AUDIO_EXTS, "음원")
        if lyrics_file is not None and lyrics_file.filename:
            _check_ext(lyrics_file.filename, LYRICS_EXTS, "가사")
        for b in bg or []:
            if b is not None and b.filename:
                _check_ext(b.filename, IMAGE_EXTS, "배경 이미지")
    except UploadError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    job_title = title.strip() or os.path.splitext(audio.filename or "untitled")[0]
    jid, d = jobs.create_job(title=job_title)
    jobs.update(jid, shorts=shorts)

    try:
        audio_path = os.path.join(d, "audio_" + (audio.filename or "input.mp3"))
        _save_upload(audio, audio_path, MAX_AUDIO_MB)

        lyrics_path = None
        if lyrics_file is not None and lyrics_file.filename:
            lyrics_path = os.path.join(d, lyrics_file.filename)
            _save_upload(lyrics_file, lyrics_path, 2)
        elif lyrics_text.strip():
            lyrics_path = os.path.join(d, "lyrics.txt")
            with open(lyrics_path, "w", encoding="utf-8") as f:
                f.write(lyrics_text)

        bg_paths = []
        for i, b in enumerate(bg or []):
            if b is not None and b.filename:
                p = os.path.join(d, f"bg{i}_{b.filename}")
                _save_upload(b, p, MAX_IMAGE_MB)
                bg_paths.append(p)
    except UploadError as e:
        jobs.update(jid, status="error", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=400)

    opts = {
        "viz": viz,
        "shorts": shorts,
        "clip_start": clip_start,
        "clip_len": clip_len,
        "kenburns": kenburns,
        "title": title,
        "artist": artist,
        "watermark": watermark,
        "align": align,
    }

    # 재렌더(AI 편집) 때 같은 자산을 재사용하도록 경로 보관
    assets = {"audio": audio_path, "lyrics": lyrics_path, "bg": bg_paths}
    jobs.update(jid, assets=assets)

    EXECUTOR.submit(_do_render, jid, d, audio_path, lyrics_path, bg_paths, opts)
    return {"job_id": jid, "status": "queued"}


class AgentMessage(BaseModel):
    role: str
    content: str


class AgentBody(BaseModel):
    job_id: str
    message: str
    history: list[AgentMessage] = []


@app.post("/api/agent")
def agent_edit(body: AgentBody):
    job = jobs.get(body.job_id)
    if not job:
        return JSONResponse({"error": "프로젝트를 찾을 수 없습니다."}, status_code=404)
    assets = job.get("assets")
    if not assets:
        return JSONResponse({"error": "이 프로젝트에는 편집할 자산이 없습니다."}, status_code=400)

    llm_key = settings.get_key("llm_api_key")
    if not llm_key:
        return JSONResponse(
            {"error": "AI 편집 키가 없습니다. 우측 상단 ⚙️ 설정에서 Claude API 키를 입력하세요."},
            status_code=400,
        )

    cfg = settings.get_raw()
    cur_opts = job.get("opts") or {}
    history = [{"role": m.role, "content": m.content} for m in body.history]
    try:
        reply, patch = agent.edit_video(
            cur_opts, body.message, history,
            provider_name=cfg["llm_provider"], model=cfg["llm_model"],
            api_key=llm_key,
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"에이전트 오류: {e}"}, status_code=500)

    new_opts = {**cur_opts, **patch}
    njid, nd = jobs.create_job(title=job.get("title", ""))
    jobs.update(njid, assets=assets, shorts=bool(new_opts.get("shorts")))
    EXECUTOR.submit(_do_render, njid, nd, assets["audio"], assets["lyrics"],
                    assets["bg"], new_opts)
    return {"reply": reply, "job_id": njid, "options": new_opts, "patch": patch}


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": jobs.list_jobs()}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    j = jobs.get(jid)
    if not j:
        return JSONResponse({"error": "not found"}, status_code=404)
    return j


@app.get("/api/jobs/{jid}/video")
def job_video(jid: str):
    out = os.path.join(jobs.job_dir(jid), "out.mp4")
    if not os.path.exists(out):
        return JSONResponse({"error": "no video"}, status_code=404)
    return FileResponse(out, media_type="video/mp4", filename="music-video.mp4")


@app.get("/api/jobs/{jid}/thumb")
def job_thumb(jid: str):
    thumb = os.path.join(jobs.job_dir(jid), "out_thumb.jpg")
    if not os.path.exists(thumb):
        return JSONResponse({"error": "no thumbnail"}, status_code=404)
    return FileResponse(thumb, media_type="image/jpeg", filename="thumbnail.jpg")
