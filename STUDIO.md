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

옵션 필드: `viz`, `shorts`, `clip_start`, `clip_len`, `kenburns`, `title`, `artist`,
`watermark`, `align`, `lyrics_text`.

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

## 로드맵

- [x] **1. 로컬 웹 MVP** — 업로드 → 생성 → 미리보기
- [ ] 2. 프로젝트 저장 + 비동기 작업큐 + 자산 라이브러리
- [x] **3. AI 편집 에이전트** — 자연어 → tool call → 옵션 수정 → 재렌더 *(키 넣으면 동작)*
- [ ] 4. 외부 AI 영상(Kaiber/Higgsfield) 연동
- [ ] 5. **GCP 배포** — Cloud Run(백엔드) + Storage(자산) + Tasks(렌더큐), 로그인/멀티유저
