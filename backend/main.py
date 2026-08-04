"""Suno MV Studio — FastAPI 백엔드.

음원/가사/배경 업로드 -> make_mv.py 렌더 -> 비동기 잡 -> 비디오/썸네일 서빙.
프론트(Next.js, :3000)에서 호출.
"""
import hmac
import os
import tempfile
import zipfile
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

import agent
import fonts
import highlights
import jobs
import render
import settings
import storage
import video_providers
import yt_upload

STORAGE = storage.get_storage()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    jobs.load_all()
    removed = jobs.cleanup()
    if removed:
        print(f"[startup] 오래된 잡 {removed}개 정리")
    yield


app = FastAPI(title="Suno MV Studio API", lifespan=lifespan)

# 앱 토큰 인증: APP_TOKEN 이 설정된 경우에만 활성화 (로컬 개발은 미설정 = 무인증).
# 헤더(X-App-Token) 또는 쿼리(?token=) 둘 다 허용 — <video>/<img>/<a download> 는
# 커스텀 헤더를 못 붙이므로 미디어 URL 은 쿼리 방식을 쓴다.
APP_TOKEN = os.environ.get("APP_TOKEN", "")
_TOKEN_EXEMPT = {"/api/health", "/healthz", "/docs", "/openapi.json"}


@app.middleware("http")
async def _require_app_token(request, call_next):
    # CORS preflight(OPTIONS) 는 브라우저가 헤더를 못 붙이므로 통과시킨다.
    if APP_TOKEN and request.method != "OPTIONS" \
            and request.url.path not in _TOKEN_EXEMPT:
        supplied = (request.headers.get("x-app-token")
                    or request.query_params.get("token") or "")
        if not hmac.compare_digest(supplied.encode(), APP_TOKEN.encode()):
            return JSONResponse({"detail": "앱 토큰이 필요합니다"}, status_code=401)
    return await call_next(request)


# 허용 출처: 기본은 로컬, 배포 시 ALLOWED_ORIGINS(쉼표구분)로 프론트 URL 지정
# (CORSMiddleware 를 토큰 미들웨어보다 나중에 등록해야 바깥층이 되어
#  401 응답에도 CORS 헤더가 붙는다 — 프론트가 401 을 읽고 토큰 입력창을 띄움)
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
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
MAX_CLIP_MB = 80


class UploadError(Exception):
    pass


def _clip_start_ok(s: str) -> bool:
    """clip_start 가 'mm:ss'/'초' 로 파싱 가능한지 (make_mv.parse_time 과 동일 규칙)."""
    s = (s or "").strip()
    if not s:
        return True
    try:
        for p in s.split(":"):
            float(p)
        return True
    except ValueError:
        return False


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


# 실행 중 렌더 프로세스 / 대기·실행 중 Future 추적 (취소용)
_PROCS = {}      # jid -> subprocess.Popen
_FUTURES = {}    # jid -> concurrent.futures.Future


def _cancelled(jid):
    return (jobs.get(jid) or {}).get("status") == "cancelled"


def _do_render(jid, d, audio, lyrics, bg_paths, opts):
    if _cancelled(jid):
        return
    jobs.update(jid, status="running", opts=opts, progress=0, stage="")
    attempts = 2 if opts.get("auto_retry") else 1
    code, log, out = 1, "", os.path.join(d, "out.mp4")
    for attempt in range(attempts):
        if attempt > 0:
            jobs.update(jid, progress=0, stage=f"재시도 중… ({attempt + 1}/{attempts})")
        try:
            code, log, out = render.run_render(
                d, audio, lyrics, bg_paths, opts,
                on_progress=lambda p: jobs.update(jid, progress=p),
                on_proc=lambda pr: _PROCS.__setitem__(jid, pr),
            )
        except Exception as e:  # noqa: BLE001
            _PROCS.pop(jid, None)
            if not _cancelled(jid):
                jobs.update(jid, status="error", error=str(e))
            return
        _PROCS.pop(jid, None)
        if _cancelled(jid):
            return  # 취소된 잡은 결과를 덮어쓰지 않음
        if code == 0 and os.path.exists(out):
            break  # 성공 → 재시도 불필요
    try:
        log = log[-2000:]  # 잡 응답이 비대해지지 않게 끝부분만 보관
        thumb = os.path.splitext(out)[0] + "_thumb.jpg"
        has_thumb = os.path.exists(thumb)
        if code == 0 and os.path.exists(out):
            # D12: 인트로/아웃트로 클립 병합 (실패해도 본편은 유지)
            if opts.get("intro_clip") or opts.get("outro_clip"):
                try:
                    jobs.update(jid, stage="인트로/아웃트로 병합 중…")
                    render.concat_clips(out, opts.get("intro_clip"), opts.get("outro_clip"))
                except Exception as e:  # noqa: BLE001
                    print(f"[concat] 병합 실패(jid={jid}): {e}")
                jobs.update(jid, stage="")
            names = ["out.mp4"] + (["out_thumb.jpg"] if has_thumb else [])
            try:
                STORAGE.save_outputs(jid, d, names)
            except Exception as e:  # noqa: BLE001
                print(f"[storage] 업로드 실패(jid={jid}): {e}")
            jobs.update(jid, status="done", log=log, video=True,
                        thumb=has_thumb, progress=100)
        else:
            jobs.update(jid, status="error", log=log,
                        error="렌더 실패 (로그 확인)")
    except Exception as e:  # noqa: BLE001
        jobs.update(jid, status="error", error=str(e))


def _submit(fn, jid, *args):
    """렌더 작업을 큐에 넣고 Future 를 추적(취소용). 완료 시 자동 정리."""
    fut = EXECUTOR.submit(fn, *args)
    _FUTURES[jid] = fut
    fut.add_done_callback(lambda _f: _FUTURES.pop(jid, None))
    return fut


@app.get("/api/health")
@app.get("/healthz")
def health():
    return {"ok": True}


class SettingsBody(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    video_provider: str | None = None
    video_api_key: str | None = None
    llm_api_key_clear: bool | None = None    # true 면 저장된 LLM 키 삭제
    video_api_key_clear: bool | None = None  # true 면 저장된 영상 키 삭제


@app.get("/api/fonts")
def get_fonts():
    return {"fonts": fonts.list_fonts()}


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
    logo: Optional[UploadFile] = File(None),
    intro_clip: Optional[UploadFile] = File(None),
    outro_clip: Optional[UploadFile] = File(None),
    lyrics_text: str = Form(""),
    viz: str = Form("waves"),
    viz_color: str = Form(""),
    bg_style: str = Form("gradient"),
    bg_grad: str = Form(""),
    disc: bool = Form(False),
    progress_bar: bool = Form(False),
    sub_preview: bool = Form(False),
    shorts: bool = Form(False),
    clip_start: str = Form(""),
    clip_len: float = Form(30),
    kenburns: bool = Form(True),
    bg_color: str = Form("0x0a0a14"),
    title: str = Form(""),
    artist: str = Form(""),
    watermark: str = Form(""),
    align: str = Form("none"),
    res: str = Form("1080"),
    fps: int = Form(30),
    normalize: bool = Form(False),
    master: bool = Form(False),
    karaoke: bool = Form(False),
    fade_in: float = Form(0.0),
    fade_out: float = Form(0.0),
    vignette: bool = Form(False),
    film_grain: bool = Form(False),
    bg_pulse: bool = Form(False),
    sparkle: bool = Form(False),
    outro_cta: bool = Form(False),
    outro_cta_text: str = Form(""),
    sub_color: str = Form("FFFFFF"),
    sub_size: float = Form(1.0),
    sub_pos: str = Form("bottom"),
    sub_glow: bool = Form(False),
    intro_card: bool = Form(False),
    interlude_note: bool = Form(False),
    font: str = Form(""),
    auto_retry: bool = Form(True),
    preview: bool = Form(False),
):
    # 입력 검증
    try:
        _check_ext(audio.filename, AUDIO_EXTS, "음원")
        if lyrics_file is not None and lyrics_file.filename:
            _check_ext(lyrics_file.filename, LYRICS_EXTS, "가사")
        for b in bg or []:
            if b is not None and b.filename:
                _check_ext(b.filename, IMAGE_EXTS, "배경 이미지")
        if logo is not None and logo.filename:
            _check_ext(logo.filename, IMAGE_EXTS, "로고")
        for clip, lbl in ((intro_clip, "인트로 클립"), (outro_clip, "아웃트로 클립")):
            if clip is not None and clip.filename:
                _check_ext(clip.filename, VIDEO_EXTS, lbl)
    except UploadError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not _clip_start_ok(clip_start):
        return JSONResponse(
            {"error": f"클립 시작 형식 오류: '{clip_start}' (mm:ss 또는 초로 입력)"},
            status_code=400,
        )

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

        logo_path = None
        if logo is not None and logo.filename:
            logo_path = os.path.join(d, "logo_" + logo.filename)
            _save_upload(logo, logo_path, MAX_IMAGE_MB)

        intro_path = outro_path = None
        if intro_clip is not None and intro_clip.filename:
            intro_path = os.path.join(d, "intro_" + intro_clip.filename)
            _save_upload(intro_clip, intro_path, MAX_CLIP_MB)
        if outro_clip is not None and outro_clip.filename:
            outro_path = os.path.join(d, "outro_" + outro_clip.filename)
            _save_upload(outro_clip, outro_path, MAX_CLIP_MB)
    except UploadError as e:
        jobs.update(jid, status="error", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=400)

    opts = {
        "viz": viz,
        "viz_color": viz_color,
        "bg_style": bg_style,
        "bg_grad": bg_grad,
        "disc": disc,
        "progress_bar": progress_bar,
        "sub_preview": sub_preview,
        "shorts": shorts,
        "clip_start": clip_start,
        "clip_len": clip_len,
        "kenburns": kenburns,
        "bg_color": bg_color,
        "title": title,
        "artist": artist,
        "watermark": watermark,
        "align": align,
        "res": res,
        "fps": fps,
        "normalize": normalize,
        "master": master,
        "karaoke": karaoke,
        "fade_in": fade_in,
        "fade_out": fade_out,
        "vignette": vignette,
        "film_grain": film_grain,
        "bg_pulse": bg_pulse,
        "sparkle": sparkle,
        "outro_cta": outro_cta,
        "outro_cta_text": outro_cta_text,
        "sub_color": sub_color,
        "sub_size": sub_size,
        "sub_pos": sub_pos,
        "sub_glow": sub_glow,
        "intro_card": intro_card,
        "interlude_note": interlude_note,
        "font": font,
        "auto_retry": auto_retry,
        "logo": logo_path,
        "intro_clip": intro_path,
        "outro_clip": outro_path,
        "preview": preview,
    }

    # 재렌더(AI 편집) 때 같은 자산을 재사용하도록 경로 보관
    assets = {"audio": audio_path, "lyrics": lyrics_path, "bg": bg_paths}
    jobs.update(jid, assets=assets)

    _submit(_do_render, jid, jid, d, audio_path, lyrics_path, bg_paths, opts)
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
    cur_opts = {k: v for k, v in (job.get("opts") or {}).items() if k != "preview"}
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
    _submit(_do_render, njid, njid, nd, assets["audio"], assets["lyrics"],
            assets["bg"], new_opts)
    return {"reply": reply, "job_id": njid, "options": new_opts, "patch": patch}


class AiVideoBody(BaseModel):
    job_id: str
    prompt: str
    aspect: str | None = None


class StoryboardBody(BaseModel):
    job_id: str
    scenes: int = 4


def _fallback_storyboard(title, n):
    """LLM 키가 없을 때 쓰는 기본 장면 프롬프트 (분위기 순환)."""
    moods = ["dawn mist over a quiet city, cinematic wide shot",
             "sunlit clouds drifting in slow motion, dreamy",
             "neon lights reflecting on wet streets at night",
             "silhouette walking through a field at golden hour",
             "abstract flowing ink in deep water, moody",
             "stars and aurora over mountains, timelapse"]
    return [{"prompt": f"{moods[i % len(moods)]}, about '{title}', "
                       "ambient slow motion, no text, no watermark",
             "label": f"장면 {i + 1}"} for i in range(n)]


def _do_storyboard(njid, nd, assets, base_job, n_scenes, llm_cfg, vp_name, vp_key):
    """가사 -> 장면 프롬프트 -> 장면별 AI 클립 -> 크로스페이드 병합 -> 재렌더."""
    jobs.update(njid, status="running", progress=0, stage="🎬 장면 구상 중…")
    opts = {k: v for k, v in (base_job.get("opts") or {}).items() if k != "preview"}
    title = opts.get("title") or base_job.get("title", "")
    lyrics_text = _read_lyrics(assets.get("lyrics"))

    scenes = []
    if llm_cfg.get("key"):
        try:
            scenes = agent.generate_storyboard(
                title, lyrics_text, n_scenes, provider_name=llm_cfg["provider"],
                model=llm_cfg["model"], api_key=llm_cfg["key"])
        except Exception as e:  # noqa: BLE001
            print(f"[storyboard] LLM 실패, 기본 장면 사용: {e}")
    if not scenes:
        scenes = _fallback_storyboard(title, n_scenes)

    try:
        total = render._duration(assets["audio"])
    except Exception:  # noqa: BLE001
        total = 180.0
    per = max(4.0, total / len(scenes))
    shorts = bool(base_job.get("shorts"))
    aspect = "9:16" if shorts else "16:9"
    w, h = (1080, 1920) if shorts else (1920, 1080)

    clips = []
    try:
        vp = video_providers.get_video_provider(vp_name, api_key=vp_key)
        for i, sc in enumerate(scenes):
            if _cancelled(njid):
                return
            jobs.update(njid, stage=f"🎥 장면 {i + 1}/{len(scenes)} 생성 중… "
                                    f"({sc.get('label') or ''})".strip(),
                        progress=int(i / len(scenes) * 40))
            clip = os.path.join(nd, f"scene{i}.mp4")
            vp.generate(sc["prompt"], clip, duration=6, aspect=aspect)
            clips.append(clip)
        jobs.update(njid, stage="🎞️ 장면 병합 중…", progress=45)
        bg = os.path.join(nd, "storyboard_bg.mp4")
        render.concat_scene_clips(clips, [per] * len(clips), bg, w=w, h=h,
                                  fps=int(opts.get("fps", 30) or 30))
    except Exception as e:  # noqa: BLE001
        if not _cancelled(njid):
            jobs.update(njid, status="error", error=f"스토리보드 생성 실패: {e}", stage="")
        return
    jobs.update(njid, stage="", storyboard=[
        {"label": s.get("label", ""), "prompt": s.get("prompt", "")} for s in scenes])
    opts = {**opts, "video_bg": bg}
    _do_render(njid, nd, assets["audio"], assets["lyrics"], assets["bg"], opts)


@app.post("/api/storyboard")
def storyboard(body: StoryboardBody):
    """가사 기반 장면 전환 AI 뮤직비디오 (스토리보드 모드)."""
    job = jobs.get(body.job_id)
    if not job:
        return JSONResponse({"error": "프로젝트를 찾을 수 없습니다."}, status_code=404)
    assets = job.get("assets")
    if not assets:
        return JSONResponse({"error": "이 프로젝트에는 자산이 없습니다."}, status_code=400)
    cfg = settings.get_raw()
    vp_name = cfg["video_provider"]
    vp_key = settings.get_key("video_api_key")
    if not vp_key and vp_name not in video_providers.KEYLESS_PROVIDERS:
        return JSONResponse(
            {"error": "AI 영상 키가 없습니다. ⚙️ 설정에서 영상 provider API 키를 "
                      "입력하세요. (키 없이 파이프라인만 보려면 provider 를 mock 으로)"},
            status_code=400,
        )
    n = max(2, min(int(body.scenes or 4), 8))
    llm_cfg = {"provider": cfg["llm_provider"], "model": cfg["llm_model"],
               "key": settings.get_key("llm_api_key")}
    njid, nd = jobs.create_job(title=f"{job.get('title', '')} (스토리보드)")
    jobs.update(njid, assets=assets, shorts=bool(job.get("shorts")))
    _submit(_do_storyboard, njid, njid, nd, assets, job, n, llm_cfg, vp_name, vp_key)
    return {"job_id": njid, "status": "queued", "scenes": n}


def _do_ai_video(njid, nd, assets, base_job, prompt, aspect, provider_name, key):
    """AI 영상 클립 생성 -> 그 클립을 --video-bg 로 깔고 같은 자산으로 재렌더."""
    jobs.update(njid, status="running", progress=0,
                stage="🎥 AI 영상 클립 생성 중… (수십 초~수 분 소요)")
    clip_path = os.path.join(nd, "aibg.mp4")
    try:
        vp = video_providers.get_video_provider(provider_name, api_key=key)
        vp.generate(prompt, clip_path, aspect=aspect)
    except Exception as e:  # noqa: BLE001
        jobs.update(njid, status="error", error=f"AI 영상 생성 실패: {e}", stage="")
        return
    opts = {**(base_job.get("opts") or {}), "video_bg": clip_path}
    _do_render(njid, nd, assets["audio"], assets["lyrics"], assets["bg"], opts)


@app.post("/api/ai-video")
def ai_video(body: AiVideoBody):
    job = jobs.get(body.job_id)
    if not job:
        return JSONResponse({"error": "프로젝트를 찾을 수 없습니다."}, status_code=404)
    assets = job.get("assets")
    if not assets:
        return JSONResponse({"error": "이 프로젝트에는 영상에 깔 자산이 없습니다."}, status_code=400)
    if not body.prompt.strip():
        return JSONResponse({"error": "영상 프롬프트를 입력하세요."}, status_code=400)

    cfg = settings.get_raw()
    key = settings.get_key("video_api_key")
    if not key and cfg["video_provider"] not in video_providers.KEYLESS_PROVIDERS:
        return JSONResponse(
            {"error": "AI 영상 키가 없습니다. ⚙️ 설정에서 영상 provider API 키를 입력하세요."},
            status_code=400,
        )
    aspect = body.aspect or ("9:16" if job.get("shorts") else "16:9")
    njid, nd = jobs.create_job(title=job.get("title", ""))
    jobs.update(njid, assets=assets, shorts=bool(job.get("shorts")))
    _submit(_do_ai_video, njid, njid, nd, assets, job, body.prompt,
            aspect, cfg["video_provider"], key)
    return {"job_id": njid, "status": "queued"}


def _read_lyrics(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    return ""


class MetaBody(BaseModel):
    job_id: str


@app.post("/api/metadata")
def metadata(body: MetaBody):
    job = jobs.get(body.job_id)
    if not job:
        return JSONResponse({"error": "프로젝트를 찾을 수 없습니다."}, status_code=404)
    llm_key = settings.get_key("llm_api_key")
    if not llm_key:
        return JSONResponse(
            {"error": "AI 키가 없습니다. ⚙️ 설정에서 Claude API 키를 입력하세요."},
            status_code=400,
        )
    cfg = settings.get_raw()
    opts = job.get("opts") or {}
    assets = job.get("assets") or {}
    lyrics = _read_lyrics(assets.get("lyrics"))
    try:
        md = agent.generate_metadata(
            opts.get("title") or job.get("title", ""), opts.get("artist", ""),
            lyrics, provider_name=cfg["llm_provider"], model=cfg["llm_model"],
            api_key=llm_key,
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"메타데이터 생성 오류: {e}"}, status_code=500)
    if not md:
        return JSONResponse({"error": "메타데이터를 생성하지 못했습니다."}, status_code=500)
    return md


class PaletteBody(BaseModel):
    lyrics: str = ""
    title: str = ""


@app.post("/api/palette")
def palette(body: PaletteBody):
    """가사/제목 분위기 -> 파형·배경 색 팔레트 추천 (LLM)."""
    llm_key = settings.get_key("llm_api_key")
    if not llm_key:
        return JSONResponse(
            {"error": "AI 키가 없습니다. ⚙️ 설정에서 Claude API 키를 입력하세요."},
            status_code=400,
        )
    cfg = settings.get_raw()
    try:
        pal = agent.suggest_palette(
            body.title, body.lyrics, provider_name=cfg["llm_provider"],
            model=cfg["llm_model"], api_key=llm_key)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"팔레트 추천 오류: {e}"}, status_code=500)
    if not pal:
        return JSONResponse({"error": "팔레트를 추천하지 못했습니다."}, status_code=500)
    return pal


class BatchBody(BaseModel):
    job_id: str
    shorts_count: int = 3
    clip_len: float = 30.0


@app.post("/api/batch")
def batch(body: BatchBody):
    """곡 1개 -> 롱폼 1 + 후렴 쇼츠 N (각각 별도 잡으로 비동기 렌더)."""
    job = jobs.get(body.job_id)
    if not job:
        return JSONResponse({"error": "프로젝트를 찾을 수 없습니다."}, status_code=404)
    assets = job.get("assets")
    if not assets:
        return JSONResponse({"error": "이 프로젝트에는 자산이 없습니다."}, status_code=400)
    base = {k: v for k, v in (job.get("opts") or {}).items() if k != "preview"}
    title = job.get("title", "")

    # 롱폼 (전체, 세로 아님)
    lf_opts = {**base, "shorts": False, "clip_start": ""}
    lf_jid, lf_d = jobs.create_job(title=f"{title} (롱폼)")
    jobs.update(lf_jid, assets=assets, shorts=False)
    _submit(_do_render, lf_jid, lf_jid, lf_d, assets["audio"], assets["lyrics"],
            assets["bg"], lf_opts)

    # 쇼츠 (후렴 자동 감지)
    n = max(0, min(int(body.shorts_count), 6))
    # 쇼츠끼리 겹치지 않도록 최소 간격을 clip_len 이상으로
    gap = max(body.clip_len, 10.0)
    starts = highlights.detect_peaks(
        assets["audio"], n=n, clip_len=body.clip_len, min_gap=gap) if n else []
    short_jids = []
    for i, st in enumerate(starts):
        s_opts = {**base, "shorts": True, "clip_start": f"{st:.1f}",
                  "clip_len": body.clip_len}
        sjid, sd = jobs.create_job(title=f"{title} (쇼츠 {i + 1})")
        jobs.update(sjid, assets=assets, shorts=True)
        _submit(_do_render, sjid, sjid, sd, assets["audio"], assets["lyrics"],
                assets["bg"], s_opts)
        short_jids.append(sjid)

    return {"longform": lf_jid, "shorts": short_jids,
            "detected": len(short_jids)}


class TranslateBody(BaseModel):
    text: str
    target: str = "영어"
    bilingual: bool = True  # True면 원문||번역, False면 번역만


@app.post("/api/translate")
def translate(body: TranslateBody):
    lines = [ln.strip() for ln in body.text.splitlines() if ln.strip()]
    if not lines:
        return JSONResponse({"error": "번역할 가사가 없습니다."}, status_code=400)
    llm_key = settings.get_key("llm_api_key")
    if not llm_key:
        return JSONResponse(
            {"error": "AI 키가 없습니다. ⚙️ 설정에서 Claude API 키를 입력하세요."},
            status_code=400,
        )
    cfg = settings.get_raw()
    try:
        trans = agent.translate_lyrics(
            lines, target=body.target, provider_name=cfg["llm_provider"],
            model=cfg["llm_model"], api_key=llm_key)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"번역 오류: {e}"}, status_code=500)
    if body.bilingual:
        merged = [f"{o}||{t}" if t else o for o, t in zip(lines, trans)]
    else:
        merged = trans
    return {"text": "\n".join(merged), "lines": trans}


@app.get("/api/youtube/status")
def youtube_status():
    return yt_upload.auth_status()


class YouTubeBody(BaseModel):
    job_id: str
    title: str
    description: str = ""
    tags: list[str] = []
    privacy: str = "private"  # private | unlisted | public


@app.post("/api/youtube/upload")
def youtube_upload(body: YouTubeBody):
    j = jobs.get(body.job_id)
    if not j or j.get("status") != "done":
        return JSONResponse({"error": "완료된 영상만 업로드할 수 있습니다."}, status_code=400)
    p = os.path.join(jobs.job_dir(body.job_id), "out.mp4")
    if not os.path.exists(p):
        return JSONResponse({"error": "영상 파일을 찾을 수 없습니다."}, status_code=404)
    try:
        res = yt_upload.upload(p, body.title, body.description, body.tags, body.privacy)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=500)
    return res


@app.get("/api/jobs/zip")
def jobs_zip(ids: str):
    """여러 잡의 완료 영상을 한 zip 으로 묶어 다운로드 (로컬 스토리지 기준)."""
    files = []
    for jid in [x for x in ids.split(",") if x]:
        j = jobs.get(jid)
        if not j or j.get("status") != "done":
            continue
        p = os.path.join(jobs.job_dir(jid), "out.mp4")
        if os.path.exists(p):
            safe = (j.get("title") or jid).replace("/", "_").replace("\\", "_")
            files.append((p, f"{safe}_{jid}.mp4"))
    if not files:
        return JSONResponse({"error": "다운로드할 완료된 영상이 없습니다."}, status_code=400)
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for path, arc in files:
            z.write(path, arc)
    tmp.close()
    return FileResponse(
        tmp.name, media_type="application/zip", filename="music-videos.zip",
        background=BackgroundTask(lambda: os.path.exists(tmp.name) and os.remove(tmp.name)),
    )


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": jobs.list_jobs()}


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    j = jobs.get(jid)
    if not j:
        return JSONResponse({"error": "not found"}, status_code=404)
    if j["status"] in ("done", "error", "cancelled"):
        return {"ok": True, "status": j["status"]}
    # 상태를 먼저 cancelled 로 → 실행 콜백이 결과를 덮어쓰지 않음
    jobs.update(jid, status="cancelled", error="사용자가 취소함", progress=0)
    fut = _FUTURES.get(jid)
    if fut:
        fut.cancel()  # 아직 시작 안 했으면 큐에서 제거
    proc = _PROCS.get(jid)
    if proc:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "status": "cancelled"}


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    j = jobs.get(jid)
    if not j:
        return JSONResponse({"error": "not found"}, status_code=404)
    proc = _PROCS.get(jid)
    if proc:  # 실행 중이면 먼저 죽인다
        jobs.update(jid, status="cancelled")
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    fut = _FUTURES.get(jid)
    if fut:
        fut.cancel()
    jobs.remove(jid)
    return {"ok": True}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    j = jobs.get(jid)
    if not j:
        return JSONResponse({"error": "not found"}, status_code=404)
    return j


@app.get("/api/jobs/{jid}/video")
def job_video(jid: str):
    return STORAGE.serve(jid, jobs.job_dir(jid), "out.mp4", "music-video.mp4")


@app.get("/api/jobs/{jid}/thumb")
def job_thumb(jid: str):
    return STORAGE.serve(jid, jobs.job_dir(jid), "out_thumb.jpg", "thumbnail.jpg")
