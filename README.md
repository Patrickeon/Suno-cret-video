# 🎵 Suno MV Studio (music-video-maker)

음원 파일 + 가사 → **영상 + 음원 + 자막**이 한 번에 나오는 뮤직비디오 솔루션.
Suno 등 AI로 만든 곡을 유튜브에 올릴 때 사용합니다.

세 개의 레이어로 구성됩니다:

| 레이어 | 내용 | 위치 |
|---|---|---|
| 🛠️ **렌더 엔진 (CLI)** | ffmpeg 기반 뮤직비디오 생성 — 단독 사용 가능 | `make_mv.py` |
| 🌐 **웹 스튜디오** | 브라우저에서 업로드→생성→미리보기 (Next.js + FastAPI) | `frontend/`, `backend/` → **[STUDIO.md](STUDIO.md)** |
| ✨ **AI 편집 에이전트** | 자연어로 "쇼츠로 만들어줘" → Claude가 옵션 수정 → 재렌더 | `backend/agent.py` |

핵심 기능:
- 🎚️ 오디오 파형 / 스펙트럼 비주얼라이저
- 📝 가사 자막 자동 싱크 (.lrc / .txt 균등분배 / AI 강제정렬)
- 🖼️ 배경 이미지 켄 번스(줌·팬) + 다중 이미지 크로스페이드
- 📱 가로 1080p 롱폼 / 세로 9:16 쇼츠(클라이맥스 구간만) 출력
- 🏷️ 1280×720 썸네일 + 워터마크/로고 자동 생성
- 🤖 자연어 AI 편집 (Claude tool use, provider 교체 가능)

> **웹 앱 / AI 편집을 쓰려면 → [STUDIO.md](STUDIO.md)** (실행법·API·로드맵).
> 아래는 **CLI(렌더 엔진)** 사용법입니다.

---

## 설치

### 1. ffmpeg (필수)

`ffmpeg` 와 `ffprobe` 가 PATH 에 있어야 합니다.

```powershell
# Windows (winget)
winget install Gyan.FFmpeg
```
```bash
# macOS
brew install ffmpeg
# Ubuntu/Debian
sudo apt install ffmpeg
```

### 2. 코드 받기

```bash
git clone https://github.com/Patrickeon/Suno-cret-video.git
cd Suno-cret-video
```

### 3. Python 라이브러리 (선택)

> 기본 기능(영상/자막/썸네일/쇼츠)은 **추가 라이브러리가 전혀 필요 없습니다** — 표준 라이브러리 + ffmpeg 로 동작.

가사 **자동 정렬(`--align auto`)** 기능을 쓸 때만:

```bash
pip install -r requirements.txt
```

(stable-ts + torch ~2GB 를 받습니다. GPU 없으면 먼저
`pip install torch --index-url https://download.pytorch.org/whl/cpu` 로 가볍게.)

---

## 빠른 시작

리포에 동봉된 예제 자산(`examples/`)으로 바로 테스트할 수 있습니다:

```bash
# 가장 간단 (단색 배경 + 파형 + 가사)
python make_mv.py --audio examples/test.mp3 --lyrics examples/test_lyrics.txt --out mv.mp4

# 롱폼: 배경 이미지 + 썸네일 + 워터마크
python make_mv.py --audio examples/test.mp3 --lyrics examples/test_lyrics.txt \
    --bg examples/bg1.jpg --title "곡 제목" --artist "아티스트" \
    --watermark "@내채널" --out mv.mp4

# 쇼츠(세로 9:16): 2초부터 4초 구간만
python make_mv.py --audio examples/test.mp3 --lyrics examples/test_lyrics.txt \
    --bg examples/bg1.jpg --shorts --clip-start 0:02 --clip-len 4 --out short.mp4
```

실제 사용 시엔 `examples/...` 를 본인 곡/이미지 경로로 바꾸면 됩니다.

---

## 가사 싱크 — 3가지 방법

1. **`.lrc` (가장 정확)** — `[mm:ss.xx]가사` 타임코드 파일을 그대로 사용.
2. **`.txt` 균등분배 (초안, 즉시)** — 가사 줄을 곡 길이에 맞춰 자동 분배.
   `--intro`(첫 가사 전 인트로 초), `--outro`(끝 여백)로 보정.
3. **`--align auto` 강제정렬** — stable-ts 로 가사를 오디오에 맞춰 자동 정렬.

### 추천 워크플로우 (정확 + 빠름)

```bash
# 1) 자동 정렬로 초안 LRC 생성
python make_mv.py --audio song.mp3 --lyrics song.txt --align auto --lrc-out draft.lrc
# 2) draft.lrc 에서 어긋난 몇 줄만 손으로 수정
# 3) 손본 LRC로 최종 렌더
python make_mv.py --audio song.mp3 --lyrics draft.lrc --bg art.jpg --out mv.mp4
```

`.txt` 만으로 `--lrc-out` 을 쓰면 균등분배 초안 LRC가 나옵니다 (정렬 설치 없이도 가능).

---

## 옵션

| 옵션 | 설명 |
|---|---|
| `--audio` | 음원 (mp3/wav/flac) — **필수** |
| `--lyrics` | 가사 (.txt 또는 .lrc) |
| `--bg a.jpg b.jpg ...` | 배경 이미지 (여러 장이면 크로스페이드) |
| `--out` | 출력 mp4 (기본 mv.mp4) |
| `--viz` | `waves`(기본) / `cqt` / `spectrum` / `none` |
| `--no-kenburns` | 배경 줌/팬 끄기 (기본 켜짐) |
| `--shorts` | 세로 9:16 (1080×1920) 출력 |
| `--clip-start` / `--clip-len` | 구간 추출 (`1:05` 또는 초, 기본 길이 30s) |
| `--title` / `--artist` | 주면 1280×720 썸네일 자동 생성 |
| `--watermark` | 우하단 워터마크 텍스트 |
| `--logo logo.png` | 우하단 로고 (watermark보다 우선) |
| `--align auto` | stable-ts 가사 강제정렬 |
| `--align-model` | 정렬 모델 (tiny/base/small/medium, 기본 base) |
| `--lrc-out` | 초안 LRC만 만들고 종료 |
| `--font` | 자막 폰트 (기본 Malgun Gothic) |

---

## 프로젝트 구조

```
Suno-cret-video/
├── make_mv.py          # 🛠️ 렌더 엔진 (CLI)
├── requirements.txt    # (선택) 가사 자동정렬용 의존성
├── examples/           # 테스트용 샘플 음원/가사/배경
│
├── backend/            # 🌐 FastAPI 백엔드
│   ├── main.py         #   API: /api/render, /api/jobs, /api/agent
│   ├── render.py       #   make_mv.py 서브프로세스 래퍼
│   ├── jobs.py         #   잡 스토어 (인메모리)
│   ├── agent.py        #   ✨ LLM provider 추상화 + 편집 에이전트
│   └── requirements.txt
│
├── frontend/           # 🌐 Next.js 16 + React 19 스튜디오 UI
│   └── app/page.tsx    #   로컬 생성 + AI 편집 채팅
│
├── STUDIO.md           # 웹 앱 실행법 · API · 로드맵
├── README.md · LICENSE
```

웹 앱 실행/배포는 **[STUDIO.md](STUDIO.md)** 참고.

---

## 유튜브 발행 체크리스트

- [ ] **Suno 유료 플랜**에서 만든 곡인지 확인 (무료 플랜 곡은 상업 사용권 없음)
- [ ] 업로드 시 **AI 생성/변경 콘텐츠 고지** 체크
- [ ] YPP 자격: 구독자 1,000 + 시청 4,000h (또는 쇼츠 1,000만 조회/90일)
- [ ] 롱폼 1개 + 쇼츠 여러 개(클라이맥스)로 쪼개 업로드해 채널 성장
- [ ] (선택) DistroKid/TuneCore 등으로 음원 배급 + Content ID 등록

---

## 변경 내역

- **v0.3 — AI 편집 에이전트** : 자연어 → Claude tool use(`set_video_options`) → 옵션 패치 → 같은 자산으로 재렌더. `backend/agent.py` + `/api/agent` + 프론트 `AI 편집` 탭. provider 추상화로 교체 가능.
- **v0.2 — 웹 스튜디오** : Next.js 프론트 + FastAPI 백엔드. 업로드→비동기 렌더 잡→미리보기/다운로드. (자세히: [STUDIO.md](STUDIO.md))
- **v0.1 — 렌더 엔진(CLI)** : ffmpeg 비주얼라이저 + 가사 자막 + 켄번스 + 쇼츠/클립 추출 + 썸네일/워터마크 + 가사 정렬(.lrc/.txt/stable-ts).

## 로드맵

- [x] 1. 렌더 엔진 (CLI)
- [x] 2. 로컬 웹 스튜디오 (업로드 → 생성 → 미리보기)
- [x] 3. AI 편집 에이전트 (Claude, 크레딧 필요)
- [ ] 4. 외부 AI 영상 (Kaiber / Higgsfield) 연동
- [ ] 5. GCP 배포 (Cloud Run + Storage)

## License

MIT

