# Claude CLI Prompt Set - Suno MV Studio

These prompts assume the provided `CLAUDE.md` and `.claude/agents/` files are installed in the project.

## 1. First Session / Project Re-grounding

Use this after installing the new Claude configuration.

```text
현재 프로젝트를 신규 설계하지 말고, 기존 구현을 기준으로 다시 파악해줘.

먼저 CLAUDE.md를 기준으로 다음만 확인해:
- make_mv.py의 렌더 파이프라인
- backend/main.py -> backend/render.py -> make_mv.py 옵션 전달 흐름
- frontend/app/page.tsx의 주요 사용자 흐름
- 가사 싱크 방식
- AI storyboard / AI video 흐름

코드 수정은 아직 하지 마.

그 다음 내가 원하는 제품 방향을 현재 코드와 연결해서 정리해줘:
1. 일반 유튜브 플레이리스트 느낌의 장시간 영상
2. 가사와 곡 분위기에 맞는 뮤직비디오 느낌
3. 두 스타일을 섞은 Hybrid 형태

현재 기능으로 바로 가능한 것 / 구조만 조금 바꾸면 되는 것 / 새 기능이 필요한 것을 구분해줘.
답변은 구현 우선순위 중심으로 간결하게 정리해.
```

## 2. Normal Bug / Modification Prompt

```text
다음 문제를 기존 구조를 최대한 유지하면서 수정해줘:

[여기에 문제 입력]

수정 전에 관련 호출 흐름과 영향 범위를 확인하고, 원인을 찾은 뒤 최소 변경으로 고쳐.
요청하지 않은 리팩터링은 하지 마.
수정 후 관련 테스트/린트/타입체크를 실행하고 결과를 알려줘.
```

## 3. Frontend / UX Change Prompt

```text
studio-frontend 관점으로 다음 UI/UX를 수정해줘:

[여기에 UI 요청 입력]

이 앱은 일반 관리자 화면이 아니라 음악 영상 제작 스튜디오야.
사용자가 기술적인 FFmpeg 옵션을 이해하지 않아도 자연스럽게 사용할 수 있게 해줘.
기존 API와 렌더 옵션을 먼저 확인하고, UI만 바꾸고 실제 렌더가 안 바뀌는 가짜 기능은 만들지 마.
모바일/데스크톱과 loading/error/progress 상태도 유지해.
```

## 4. FFmpeg / Rendering Prompt

```text
media-engineer 관점으로 다음 렌더링 문제/기능을 처리해줘:

[여기에 렌더 요청 입력]

make_mv.py의 입력 순서, filter_complex label, audio/video duration, clip offset, subtitles, fps를 먼저 확인해.
기존 CLI 옵션은 가능한 유지하고 새 옵션이 필요하면 backward-compatible하게 추가해.
수정 후 테스트와 짧은 preview render로 검증해.
```

## 5. Lyrics Sync Prompt

```text
media-engineer 관점으로 가사 싱크를 개선해줘.

목표:
[현재 증상 또는 원하는 개선 입력]

단순히 전체 timestamp에 임의의 offset을 더하거나 빼는 방식부터 적용하지 마.
다음 경로를 추적해서 실제 원인을 찾아:
audio seek/trim -> stable-ts 또는 LRC -> cue 생성 -> clip cue slicing -> ASS -> 최종 render/preview.

원본 가사 문장은 타이밍 수정과 분리해서 보존하고, LLM이 시간을 추측하게 만들지 마.
```

## 6. Playlist Style Feature Prompt

```text
creative-director와 studio-frontend 관점으로 'Playlist Mode'를 개선해줘.

목표는 유튜브의 장시간 플레이리스트 영상처럼 오래 봐도 피곤하지 않고, 채널 고유의 분위기가 유지되는 영상이야.

기존 기능(앨범아트, gradient, Ken Burns, disc, visualizer, lyrics, progress, palette)을 최대한 재사용해.
새로운 효과를 많이 추가하기보다 아래를 우선해:
- 안정적인 화면 구성
- 느린 모션
- 일관된 색감
- 가사 가독성
- 곡 전체에서 자연스러운 움직임
- 장시간 시청 피로도 감소

먼저 어떤 기존 옵션을 묶으면 Playlist Mode가 되는지 설계하고, 가장 작은 코드 변경으로 구현해.
```

## 7. Music Video Style Feature Prompt

```text
creative-director와 media-engineer 관점으로 Music Video Mode를 개선해줘.

현재 storyboard가 단순히 N개의 AI 장면을 곡 길이에 균등 배치하는 부분부터 확인해.
목표는 장면 수를 늘리는 것이 아니라 곡의 감정 흐름과 가사에 맞는 장면 전환이야.

우선순위:
1. intro / verse / chorus / bridge / climax / outro 또는 유효한 대체 구간 탐지
2. 각 구간에 scene purpose와 timestamp 부여
3. 공통 palette / subject rule / camera language 유지
4. 구간에 맞는 AI prompt 생성
5. xfade 또는 다른 transition을 실제 timestamp에 맞춰 적용

기존 storyboard API를 깨지 않는 점진적 확장안을 먼저 제시한 뒤 구현해.
```

## 8. Hybrid Mode - Recommended Next Feature

```text
이 프로젝트에 Hybrid Mode를 추가해줘.

정의:
- 기본 화면은 플레이리스트처럼 안정적으로 유지한다.
- 모든 순간을 AI 영상으로 바꾸지 않는다.
- intro, chorus, bridge, climax처럼 의미 있는 구간에만 cinematic scene/background를 사용한다.
- 가사, 앨범아트 또는 다른 visual anchor가 영상 정체성을 계속 유지한다.

먼저 현재 코드에서 재사용할 수 있는 기능을 찾아.
그 다음 visual_mode 같은 상위 개념이 필요한지 판단하고, 필요하면 기존 low-level options로 매핑되도록 설계해.

초기 버전은 과도하게 복잡하게 만들지 말고 기존 API/CLI와 호환되게 구현해.
```

## 9. True Multi-song Playlist Prompt

```text
현재 '앨범 일괄 렌더'는 여러 곡을 각각 따로 렌더하는 기능이야.
이 기능은 유지하면서, 별도로 여러 곡을 하나의 긴 YouTube Playlist 영상으로 합치는 기능을 설계해줘.

필요 개념:
- Track[]
- 각 곡 duration과 local timeline
- 전체 global timeline
- 곡 사이 transition
- 전체에서 유지되는 visual identity
- 현재 곡 제목/아티스트 표시
- 선택적으로 lyrics
- YouTube chapter용 track timestamps

기존 batch 기능을 다른 의미로 바꾸지 말고 새 기능으로 확장해.
먼저 데이터 구조/API/render 흐름을 설계하고 영향 범위를 확인한 뒤 구현해.
```

## 10. Autonomous Continuation Prompt

```text
현재 목표와 CLAUDE.md 기준으로 다음 작업을 이어서 진행해.

규칙:
- 매번 나에게 사소한 선택을 묻지 마.
- 현재 코드와 테스트를 기준으로 가장 합리적인 선택을 해.
- 한 번에 너무 넓은 리팩터링을 하지 마.
- 기능 하나를 실제 동작 가능한 상태로 끝내고 검증한 뒤 다음 작업으로 넘어가.
- destructive git 작업, 사용자 자산 삭제, 유료 외부 API 추가가 필요한 경우에만 멈추고 알려줘.
- 작업 완료 시 변경 파일, 검증 결과, 다음 추천 작업만 짧게 알려줘.
```

## Recommended First Prompt

If the immediate goal is “다른 유튜버들의 플리처럼 보이면서도 필요하면 뮤직비디오 느낌을 내는 것”, start with this:

```text
현재 프로젝트에 상위 Visual Mode 개념을 설계하고 1차 구현해줘.

필요한 모드는 최소 3개:
- Playlist
- Hybrid
- Music Video

중요:
기존 렌더 엔진을 다시 만들지 마.
각 모드는 우선 현재 존재하는 옵션들을 의미 있는 조합으로 묶는 방식으로 시작해.

Playlist는 안정적이고 장시간 시청에 적합하게,
Hybrid는 안정적인 화면에 중요한 구간만 cinematic하게,
Music Video는 storyboard/AI scene 중심으로 동작하게 해.

현재 frontend/backend/make_mv 구조를 조사해서 가장 자연스러운 데이터 흐름을 정하고,
API/CLI backward compatibility를 유지해.

1차 구현에서는 복잡한 자동 구간 분석까지 한꺼번에 넣지 말고,
Visual Mode의 UX와 option mapping을 먼저 완성하고 테스트해.
그 다음 2차 단계로 music-aware scene timing을 제안해.
```
