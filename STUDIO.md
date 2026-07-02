# 🎬 Suno MV Studio (웹 앱)

`make_mv.py` 렌더 엔진을 웹 UI로 감싼 영상 스튜디오. 브라우저에서 음원·가사·배경을
업로드하면 백엔드가 렌더해 영상/썸네일을 돌려준다.

> 장기 목표: "Cursor for 비디오 편집" — 자연어로 영상을 수정하는 AI 에이전트 + 외부 AI
> 영상 생성(Kaiber/Higgsfield) 연동 + GCP 배포. (로드맵은 아래 참고)

## 구조

```
frontend/   Next.js 16 + React 19 + Tailwind (브라우저 UI)
backend/    FastAPI (Python) — make_mv.py 렌더 + 잡 관리 + (예정)AI 에이전트
  ├ main.py    API: /api/render, /api/jobs/{id}, .../video, .../thumb
  ├ render.py  make_mv.py 서브프로세스 래퍼
  ├ jobs.py    인메모리 잡 스토어 (추후 DB/Cloud Tasks)
  └ agent.py   LLM provider 추상화 (Claude, 교체 가능)
make_mv.py  렌더 엔진 (CLI 로도 단독 사용 가능)
```

## 실행 (로컬, 터미널 2개)

**1) 백엔드** (포트 8000)
```bash
cd backend
pip install -r requirements.txt          # 최초 1회
python -m uvicorn main:app --port 8000
```

**2) 프론트엔드** (포트 3000)
```bash
cd frontend
npm install                              # 최초 1회
npm run dev
```

→ 브라우저에서 **http://localhost:3000** 접속.
음원(필수) + 가사(텍스트/파일) + 배경 이미지 업로드 → 옵션 설정 → **생성** → 미리보기/다운로드.

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/render` | 멀티파트 업로드(audio/lyrics_file/bg[]) + 옵션 → `{job_id}` |
| GET | `/api/jobs/{id}` | 잡 상태 (queued/running/done/error) + 로그 |
| GET | `/api/jobs/{id}/video` | 결과 mp4 |
| GET | `/api/jobs/{id}/thumb` | 썸네일 jpg |
| POST | `/api/ai-video` | `{job_id, prompt}` → AI 영상 클립 생성 후 `--video-bg`로 재렌더 |

옵션 필드: `viz`, `shorts`, `clip_start`, `clip_len`, `kenburns`, `bg_color`, `title`,
`artist`, `watermark`, `align`, `lyrics_text`.

렌더 진행률은 잡 응답의 `progress`(0~100)로 노출된다 — make_mv 가 ffmpeg `-progress`를
파싱해 `MV_PROGRESS`로 흘리고, 백엔드가 잡에 반영, 프론트가 결정형 진행바로 표시.

## 환경변수

- 프론트: `frontend/.env.local` → `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000`
- 백엔드(AI 에이전트용, 예정): `ANTHROPIC_API_KEY`

## AI 편집 에이전트 (Phase 3)

`AI 편집 ✨` 탭에서 자연어로 현재 프로젝트를 수정한다. 흐름:

1. 먼저 `로컬 생성`으로 기본 영상(프로젝트) 생성 → 자산(음원/가사/배경)이 잡에 보관됨
2. AI 탭에서 "쇼츠로 만들어줘", "스펙트럼으로 바꿔줘" 등 입력
3. 백엔드 `/api/agent` → Claude가 `set_video_options` 도구로 바뀔 옵션만 패치
4. 같은 자산 + 새 옵션으로 재렌더 → 미리보기 갱신

**사용 전 준비:** 백엔드에 API 키 필요.
```bash
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m uvicorn main:app --port 8000   # 키를 읽은 채로 재시작
```
키가 없으면 채팅에 안내 메시지가 뜨고, 로컬 생성은 키 없이도 동작한다.
provider는 `agent.py`에서 교체 가능(Claude 기본).

## 외부 AI 영상 연동 (Phase 4)

AI가 생성한 영상 클립을 **배경 트랙**으로 깔고, 그 위에 비주얼라이저/자막을 얹는다.

```
프롬프트 → [AI 영상 provider] → clip.mp4 → make_mv --video-bg clip.mp4 → 최종 뮤직비디오
```

- `make_mv.py --video-bg <clip.mp4>` : 영상 배경 지원(루프+cover-crop). **구현·검증 완료**
- `backend/render.py` : `opts["video_bg"]` 면 `--video-bg` 로 전달. **연결됨**
- `/api/ai-video` + 프론트 `AI 편집 ✨` 탭의 **🎥 AI 배경 영상** 입력 — 프롬프트 한 줄로
  클립 생성→재렌더까지. **연결 완료** (영상 provider 키 필요).
- `backend/video_providers.py` :
  - **Replicate** (`ReplicateProvider`, 기본·권장) — 실제 동작. `REPLICATE_API_TOKEN`,
    모델은 `REPLICATE_MODEL`(기본 `minimax/video-01`)로 교체 가능.
  - Kaiber / Higgsfield — submit→poll→download **스텁**. API 사양 받으면 `_submit`/`_poll`만 채우면 동작.

> 비용/품질 확인 후 Kaiber·Higgsfield·fal.ai 등으로 provider 교체 가능 (UI ⚙️ 또는 환경변수).

## GCP 배포 (Phase 5, 골격)

- `backend/Dockerfile` (ffmpeg + NanumGothic), `frontend/Dockerfile` (Next standalone)
- `MV_FONT`(컨테이너 한글 폰트), `ALLOWED_ORIGINS`(CORS), `ANTHROPIC_API_KEY` 환경변수화
- 배포 절차/주의사항(임시 FS·잡 스토어·Secret Manager 등): **[DEPLOY.md](DEPLOY.md)**

## 고도화 (적용됨)

- **잡 영속화** — `jobs.py` 가 잡별 `job.json` 저장 → 재시작에도 복구. `/api/jobs` 목록 + UI "최근 작업".
- **입력 검증** — 형식 허용목록(오디오/이미지/가사) + 크기 제한(음원 60MB, 이미지 15MB).
- **자동 정리** — 시작 시 오래된 잡(24h/50개 초과) TTL 정리.
- **BYOK** — UI ⚙️ 에서 키/모델/provider 런타임 설정 (키 마스킹, 환경변수 폴백).
- **컨테이너화** — `docker compose up --build` 로 프로덕션 동일 구성 로컬 검증 완료
  (백엔드 ffmpeg+NanumGothic 한글자막 렌더까지 컨테이너에서 확인).
- **렌더 진행률** — ffmpeg `-progress` 파싱 → 잡 `progress`(0~100) → 결정형 진행바.
- **비주얼 프리셋** — Lo-fi/발라드/EDM/미니멀 1클릭(viz·kenburns·bg_color 조합).
- **AI 편집 도구 확장** — `bg_color/align/intro/outro`까지 자연어로 변경 가능.
- **모델 선택 UI** — Opus 4.8 / Sonnet 4.6 / Haiku 4.5 드롭다운 + 직접 입력.
- **AI 배경 영상(Replicate)** — 프롬프트→클립→재렌더 동작(키 입력 시).
- **프론트 분리** — `page.tsx` → `components/ui`, `components/SettingsModal`, `lib/studio`.
- **백엔드 테스트** — `backend/tests/` pytest 36케이스(파싱/명령빌드/에이전트/잡/provider/하이라이트).
- **오디오 품질** — -14 LUFS 라우드니스 정규화 + 인트로/아웃트로 페이드(영상+오디오).
- **유튜브 인코딩** — 1080/1440/4K 출력(1440p↑는 VP9 유도), 24/30/60fps, `high` 프로파일, `+faststart`, 48kHz 오디오.
- **비주얼** — `bars`(컬러 주파수 막대) 비주얼라이저, 비네트, 필름 그레인.
- **발행** — `/api/metadata`(제목·설명·태그·챕터 LLM 생성), `/api/batch`(astats 후렴 감지 → 롱폼1+쇼츠N 자동), UI ‘🚀 유튜브 발행’ 패널.
- **입력 검증** — 잘못된 clip_start 즉시 400(파이썬 traceback 방지), 가사 BOM 제거.
- **자막 스타일** — 색(RRGGBB)·크기·위치(하단/중앙/상단) + `🎤 카라오케` 색채움(\\kf).
- **잡 취소/삭제** — 실행 중 ffmpeg kill 취소 + 삭제(`/api/jobs/{id}/cancel`, `DELETE`).
- **오디오 마스터링** — 2-pass loudnorm(정밀 -14 LUFS) + 리미터(`--master`).
- **프리셋/ZIP** — 스타일·품질 조합 프리셋 저장/불러오기(localStorage), 배치 결과 일괄 ZIP(`/api/jobs/zip`).
- **YouTube 업로드** — `/api/youtube/upload`(OAuth). 설정은 `backend/yt_upload.py` 주석 참고(선택 의존성 `requirements-youtube.txt`).
- **빠른 미리보기** — `--preview-secs`: 앞 N초만 720p·ultrafast 렌더(옵션 반복 확인용).
- **채널 브랜딩** — 로고(우하단, 워터마크 우선) 웹 업로드 노출.
- **다국어 자막** — `/api/translate`(LLM) → 원문||번역 이중 자막(`||`=자막 줄바꿈).
- **가사 탭-싱크** — 재생하며 줄마다 탭 → LRC 생성/적용(파형 없이 즉시).
- **앨범 모드** — 여러 곡을 같은 스타일로 일괄 렌더(제목=파일명).
- **글로우 자막** — `--sub-glow`(ASS blur 발광).
- **인트로 타이틀 카드** — `--intro-card`(시작 ~4초 제목/아티스트 페이드인).
- **간주 ♪** — `--interlude-note`(가사 없는 긴 구간에 ♪).
- **자막 폰트 선택** — `/api/fonts` 시스템 폰트 스캔 + `--font`.
- **모바일 반응형** — 헤더/그리드/배경선택기 작은 화면 대응.

## 로드맵

- [x] **1. 로컬 웹 MVP** — 업로드 → 생성 → 미리보기
- [x] **2. 영속화/검증/정리 + 히스토리** *(작업큐 분리는 향후)*
- [x] **3. AI 편집 에이전트** — 자연어 → tool call → 옵션 수정 → 재렌더 *(키 넣으면 동작)*
- [x] **4. 외부 AI 영상** — Replicate provider 동작 + `/api/ai-video` + UI 연결 *(Kaiber/Higgsfield는 스텁 유지)*
- [~] **5. GCP 배포** — Dockerfile·compose·cloudbuild·가이드 완료, 실제 `gcloud run deploy`·GCS 이전 남음
