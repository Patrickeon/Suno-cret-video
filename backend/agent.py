"""LLM provider 추상화 — AI 편집 에이전트의 '두뇌'.

Claude로 시작하되, 다른 provider로 교체 가능하도록 인터페이스를 분리한다.
(Phase 3 에서 이 위에 '자연어 -> 편집 도구 호출' 에이전트를 구현)
"""
import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """모든 LLM provider 가 구현해야 하는 공통 인터페이스."""

    @abstractmethod
    def chat(self, system, messages, tools=None, max_tokens=2048):
        """대화 한 턴 실행. provider 별 응답 객체를 반환."""
        raise NotImplementedError


class ClaudeProvider(LLMProvider):
    """Anthropic Claude. tool use(도구 호출)에 강해 편집 에이전트에 적합."""

    def __init__(self, model="claude-sonnet-4-6", api_key=None):
        import anthropic
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        self.model = model

    def chat(self, system, messages, tools=None, max_tokens=2048):
        return self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools or [],
        )


# 다른 provider 추가 시 여기에 등록 (예: OpenAIProvider)
_PROVIDERS = {
    "claude": ClaudeProvider,
}


def get_provider(name="claude", **kwargs):
    name = (name or "claude").lower()
    if name not in _PROVIDERS:
        raise ValueError(f"unknown LLM provider: {name} (available: {list(_PROVIDERS)})")
    return _PROVIDERS[name](**kwargs)


# ─────────────────────────────────────────────────────────────
# 영상 편집 에이전트 — 자연어 -> 옵션 변경(tool call)
# ─────────────────────────────────────────────────────────────

# Claude 가 호출할 도구: 바꿀 옵션만 채워서 호출한다.
EDIT_TOOL = {
    "name": "set_video_options",
    "description": "뮤직비디오 렌더 옵션을 변경한다. 사용자가 요청한, 바뀌어야 하는 필드만 포함할 것.",
    "input_schema": {
        "type": "object",
        "properties": {
            "viz": {"type": "string",
                    "enum": ["waves", "bars", "line", "cqt", "spectrum", "none"],
                    "description": "비주얼라이저: waves=글로우 파형(기본), bars=그라데이션 막대, "
                                   "line=미니멀 라인(잔잔한 곡), cqt/spectrum=스펙트럼"},
            "viz_color": {"type": "string",
                          "description": "비주얼라이저 그라데이션 색 1~2개, 쉼표 구분 RRGGBB "
                                         "(예: 'FDA4AF,FECDD3'=핑크, 곡 분위기에 맞춰 선택)"},
            "bg_style": {"type": "string", "enum": ["gradient", "solid"],
                         "description": "배경 이미지가 없을 때: gradient=흐르는 그라데이션(기본), solid=단색"},
            "bg_grad": {"type": "string",
                        "description": "그라데이션 배경 색 2~3개, 쉼표 구분 RRGGBB (어두운 톤 권장)"},
            "disc": {"type": "boolean",
                     "description": "레코드 모드: 원형 앨범아트(첫 배경 이미지)가 중앙에서 회전"},
            "progress_bar": {"type": "boolean", "description": "하단 곡 진행바"},
            "sub_preview": {"type": "boolean",
                            "description": "다음 소절 미리보기 (현재 가사 아래 작고 흐리게)"},
            "shorts": {"type": "boolean", "description": "세로 9:16 쇼츠 여부"},
            "clip_start": {"type": "string",
                           "description": "클립 시작 시각 'mm:ss' 또는 초. 전체면 빈 문자열"},
            "clip_len": {"type": "number", "description": "클립 길이(초)"},
            "kenburns": {"type": "boolean", "description": "배경 줌/팬 효과"},
            "title": {"type": "string", "description": "썸네일 제목"},
            "artist": {"type": "string", "description": "아티스트명"},
            "watermark": {"type": "string", "description": "우하단 워터마크 텍스트"},
            "bg_color": {"type": "string",
                         "description": "배경이 단색일 때 색 (ffmpeg 색명 또는 0xRRGGBB, 예: black, 0x0a0a14)"},
            "align": {"type": "string", "enum": ["none", "auto"],
                      "description": "auto면 stable-ts로 가사를 오디오에 강제정렬(백엔드에 설치돼 있어야 함)"},
            "intro": {"type": "number",
                      "description": "txt 가사 균등분배 시 첫 가사 전 인트로(초)"},
            "outro": {"type": "number",
                      "description": "txt 가사 균등분배 시 끝 여백(초)"},
            "res": {"type": "string", "enum": ["1080", "1440", "2160"],
                    "description": "출력 해상도(세로). 1440/2160 은 유튜브에서 더 선명"},
            "fps": {"type": "integer", "enum": [24, 30, 60],
                    "description": "프레임레이트. 60 이면 비주얼라이저가 부드러움"},
            "normalize": {"type": "boolean",
                          "description": "유튜브 기준 -14 LUFS 라우드니스 정규화(1-pass)"},
            "master": {"type": "boolean",
                       "description": "정밀 마스터링(2-pass loudnorm + 리미터)"},
            "karaoke": {"type": "boolean",
                        "description": "가사 카라오케 색채움 효과"},
            "fade_in": {"type": "number", "description": "인트로 페이드 길이(초, 영상+오디오)"},
            "fade_out": {"type": "number", "description": "아웃트로 페이드 길이(초, 영상+오디오)"},
            "vignette": {"type": "boolean", "description": "비네트(가장자리 어둡게)"},
            "film_grain": {"type": "boolean", "description": "필름 그레인 질감"},
            "sparkle": {"type": "boolean",
                        "description": "은은하게 떠다니는 ♪ 파티클 배경 장식"},
            "outro_cta": {"type": "boolean",
                          "description": "곡 끝 ~4초에 구독/좋아요 유도 카드 페이드인"},
            "outro_cta_text": {"type": "string",
                                "description": "아웃트로 카드 문구 (예: '구독과 좋아요 부탁드려요')"},
            "sub_color": {"type": "string",
                          "description": "자막 색 RRGGBB 16진 (예: FFD700=골드)"},
            "sub_size": {"type": "number", "description": "자막 크기 배율 (1.0 기본)"},
            "sub_pos": {"type": "string", "enum": ["bottom", "middle", "top"],
                        "description": "자막 세로 위치"},
        },
    },
}

EDIT_SYSTEM = """당신은 뮤직비디오 편집 어시스턴트입니다.
사용자의 자연어 요청을 받아 set_video_options 도구로 렌더 옵션을 변경합니다.

규칙:
- 바꿔야 하는 필드만 도구 입력에 넣으세요 (바뀌지 않는 값은 생략).
- 요청이 옵션 변경과 무관하면 도구를 호출하지 말고 짧게 안내만 하세요.
- 도구 호출 후에는 무엇을 어떻게 바꿨는지 한국어로 1~2문장으로 짧게 설명하세요.
- "원래대로/전체로 되돌려"처럼 해제 요청이면 해당 필드를 기본값으로(clip_start="", shorts=false 등) 설정하세요.
- clip_start는 'mm:ss' 또는 초 문자열이며 빈 문자열이면 곡 전체입니다.
- bg_color는 배경 이미지가 없을 때만 의미가 있습니다."""


# ─────────────────────────────────────────────────────────────
# AI 자동 팔레트 — 가사 분위기 -> 파형/배경 색 추천
# ─────────────────────────────────────────────────────────────

PALETTE_TOOL = {
    "name": "set_palette",
    "description": "곡 분위기에 맞는 뮤직비디오 색 팔레트를 지정한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "viz_color": {"type": "string",
                          "description": "비주얼라이저 그라데이션 색 2개, 쉼표 구분 RRGGBB "
                                         "(예: '7DD3FC,F0ABFC'). 밝고 채도 있는 파스텔~네온 톤"},
            "bg_grad": {"type": "string",
                        "description": "배경 그라데이션 색 3개, 쉼표 구분 RRGGBB. "
                                       "어두운 톤(자막 가독성), viz_color 와 조화"},
            "viz": {"type": "string", "enum": ["waves", "bars", "line"],
                    "description": "어울리는 비주얼라이저 (잔잔=line, 기본=waves, 신남=bars)"},
            "mood": {"type": "string", "description": "분위기 한 단어 (예: 몽환적, 신나는)"},
        },
        "required": ["viz_color", "bg_grad", "mood"],
    },
}

PALETTE_SYSTEM = """당신은 뮤직비디오 아트디렉터입니다. 곡 제목과 가사의 분위기를 읽고
set_palette 도구로 어울리는 색 팔레트를 지정하세요.
- viz_color: 화면에서 빛나는 파형 색 — 밝은 파스텔/네온 2색 그라데이션.
- bg_grad: 배경 3색 — 어둡게 유지해 흰 자막이 잘 읽히게 (밝기 낮은 딥 톤).
반드시 도구를 호출하세요."""


def suggest_palette(title, lyrics, provider_name="claude", model=None, api_key=None):
    """곡 정보 -> {viz_color, bg_grad, viz, mood}. 도구 미호출 시 빈 dict."""
    kw = {}
    if model:
        kw["model"] = model
    if api_key:
        kw["api_key"] = api_key
    provider = get_provider(provider_name, **kw)
    user = (f"제목: {title or '(미정)'}\n\n가사:\n{(lyrics or '(없음)')[:2000]}")
    resp = provider.chat(PALETTE_SYSTEM, [{"role": "user", "content": user}],
                         tools=[PALETTE_TOOL])
    for b in resp.content:
        if b.type == "tool_use" and b.name == "set_palette":
            return dict(b.input or {})
    return {}


# ─────────────────────────────────────────────────────────────
# AI 스토리보드 — 가사 -> 장면별 text-to-video 프롬프트
# ─────────────────────────────────────────────────────────────

STORYBOARD_TOOL = {
    "name": "set_storyboard",
    "description": "뮤직비디오 스토리보드(장면별 영상 생성 프롬프트)를 지정한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "description": "곡 흐름 순서대로, 요청된 개수만큼의 장면",
                "items": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string",
                                   "description": "text-to-video 용 영어 프롬프트. 카메라·조명·"
                                                  "분위기 포함, 텍스트/자막/로고 금지"},
                        "label": {"type": "string", "description": "장면 한 줄 요약 (한국어)"},
                    },
                    "required": ["prompt"],
                },
            },
            "style": {"type": "string",
                      "description": "전 장면을 관통하는 비주얼 스타일 한 줄 (영어)"},
        },
        "required": ["scenes"],
    },
}

STORYBOARD_SYSTEM = """당신은 뮤직비디오 감독입니다. 곡 제목과 가사를 읽고
set_storyboard 도구로 장면별 text-to-video 프롬프트를 만드세요.

규칙:
- 요청된 장면 수를 정확히 지키세요. 곡의 감정 흐름(도입→전개→클라이맥스→마무리)을 따라가세요.
- 모든 장면이 하나의 뮤직비디오처럼 보이도록 색감·주인공·스타일을 통일하고,
  그 공통 스타일 문구를 각 프롬프트 끝에 반복해 붙이세요.
- 프롬프트는 영어로, 카메라 움직임·조명·분위기를 구체적으로. 인물 클로즈업보다
  분위기 샷(풍경/실루엣/추상)을 선호 — AI 영상의 얼굴 왜곡을 피합니다.
- 영상 안에 글자·자막·로고가 나오지 않게 "no text, no watermark"를 포함하세요.
- 배경으로 깔리는 영상이므로 루프에 어울리는 잔잔한 모션(slow motion, ambient)으로.
반드시 도구를 호출하세요."""


def generate_storyboard(title, lyrics, n_scenes=4, provider_name="claude",
                        model=None, api_key=None):
    """곡 정보 -> [{prompt, label}, ...] (n_scenes 개). 도구 미호출 시 빈 리스트."""
    kw = {}
    if model:
        kw["model"] = model
    if api_key:
        kw["api_key"] = api_key
    provider = get_provider(provider_name, **kw)
    user = (f"제목: {title or '(미정)'}\n장면 수: {n_scenes}\n\n"
            f"가사:\n{(lyrics or '(가사 없음 — 분위기는 제목으로 유추)')[:2500]}")
    resp = provider.chat(STORYBOARD_SYSTEM, [{"role": "user", "content": user}],
                         tools=[STORYBOARD_TOOL])
    for b in resp.content:
        if b.type == "tool_use" and b.name == "set_storyboard":
            scenes = list((b.input or {}).get("scenes") or [])
            scenes = [s for s in scenes if (s or {}).get("prompt")]
            return scenes[:n_scenes] if scenes else []
    return []


# ─────────────────────────────────────────────────────────────
# 유튜브 메타데이터 생성 — 제목/설명/태그/챕터
# ─────────────────────────────────────────────────────────────

METADATA_TOOL = {
    "name": "set_youtube_metadata",
    "description": "유튜브 업로드용 메타데이터를 생성한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "클릭을 부르는 유튜브 제목 (100자 이내)"},
            "description": {"type": "string",
                            "description": "설명란 본문 (3~5문장 + 해시태그 몇 개)"},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "검색 태그 10~15개"},
            "chapters": {
                "type": "array",
                "description": "타임스탬프 챕터 (선택). 없으면 빈 배열",
                "items": {
                    "type": "object",
                    "properties": {
                        "time": {"type": "string", "description": "mm:ss"},
                        "label": {"type": "string"},
                    },
                },
            },
        },
        "required": ["title", "description", "tags"],
    },
}

METADATA_SYSTEM = """당신은 유튜브 뮤직비디오 채널 운영자를 돕는 메타데이터 전문가입니다.
주어진 곡 정보(제목/아티스트/가사)를 바탕으로 set_youtube_metadata 도구를 호출해
한국어 위주의 매력적인 제목·설명·태그를 만드세요. 과장/낚시는 피하고, 설명 끝에
관련 해시태그 3~5개를 넣으세요. 반드시 도구를 호출하세요."""


def generate_metadata(title, artist, lyrics, provider_name="claude",
                      model=None, api_key=None):
    """곡 정보 -> 유튜브 메타데이터 dict. 도구 미호출 시 빈 dict."""
    kw = {}
    if model:
        kw["model"] = model
    if api_key:
        kw["api_key"] = api_key
    provider = get_provider(provider_name, **kw)

    user = (
        f"제목: {title or '(미정)'}\n아티스트: {artist or '(미정)'}\n\n"
        f"가사:\n{(lyrics or '(없음)')[:3000]}"
    )
    resp = provider.chat(METADATA_SYSTEM, [{"role": "user", "content": user}],
                         tools=[METADATA_TOOL])
    for b in resp.content:
        if b.type == "tool_use" and b.name == "set_youtube_metadata":
            return dict(b.input or {})
    return {}


# ─────────────────────────────────────────────────────────────
# 가사 번역 — 줄 단위, 원문과 1:1 대응
# ─────────────────────────────────────────────────────────────

TRANSLATE_TOOL = {
    "name": "set_translation",
    "description": "가사를 줄 단위로 번역한다. 입력 줄 수와 정확히 같은 개수를 반환할 것.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "items": {"type": "string"},
                      "description": "각 원문 줄의 번역 (원문과 같은 순서·개수)"},
        },
        "required": ["lines"],
    },
}


def translate_lyrics(lines, target="영어", provider_name="claude", model=None, api_key=None):
    """가사 줄 리스트 -> 번역 줄 리스트(같은 길이). 실패 시 원문 반환."""
    kw = {}
    if model:
        kw["model"] = model
    if api_key:
        kw["api_key"] = api_key
    provider = get_provider(provider_name, **kw)
    numbered = "\n".join(f"{i+1}. {ln}" for i, ln in enumerate(lines))
    system = (f"당신은 노래 가사 번역가입니다. 아래 가사를 {target}로 자연스럽게 번역하되,"
              " 각 줄을 1:1로 대응시키고 set_translation 도구로 정확히 같은 개수의 줄을 반환하세요."
              " 의미와 감성을 살리되 자막용으로 간결하게.")
    resp = provider.chat(system, [{"role": "user", "content": numbered}],
                         tools=[TRANSLATE_TOOL])
    for b in resp.content:
        if b.type == "tool_use" and b.name == "set_translation":
            out = list((b.input or {}).get("lines") or [])
            if out:
                # 길이 보정
                if len(out) < len(lines):
                    out += [""] * (len(lines) - len(out))
                return out[:len(lines)]
    return list(lines)


def _blocks_to_dicts(content):
    out = []
    for b in content:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def edit_video(current_opts, message, history=None, provider_name="claude",
               model=None, api_key=None):
    """자연어 편집 한 턴.

    반환: (reply_text, patch_dict)  patch_dict 는 변경된 옵션만.
    키 미설정 등 오류 시 예외 발생.
    """
    kw = {}
    if model:
        kw["model"] = model
    if api_key:
        kw["api_key"] = api_key
    provider = get_provider(provider_name, **kw)

    system = EDIT_SYSTEM + f"\n\n현재 옵션(JSON): {current_opts}"
    messages = list(history or [])
    messages.append({"role": "user", "content": message})

    resp = provider.chat(system, messages, tools=[EDIT_TOOL])

    patch = {}
    tool_uses = [b for b in resp.content if b.type == "tool_use"]
    if tool_uses:
        messages.append({"role": "assistant", "content": _blocks_to_dicts(resp.content)})
        results = []
        for tu in tool_uses:
            patch.update(tu.input or {})
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "적용됨"})
        messages.append({"role": "user", "content": results})
        resp2 = provider.chat(system, messages, tools=[EDIT_TOOL])
        reply = "".join(b.text for b in resp2.content if b.type == "text").strip()
    else:
        reply = "".join(b.text for b in resp.content if b.type == "text").strip()

    if not reply:
        reply = "요청을 반영했어요." if patch else "변경할 옵션을 찾지 못했어요."
    return reply, patch
