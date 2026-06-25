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
            "viz": {"type": "string", "enum": ["waves", "cqt", "spectrum", "none"],
                    "description": "비주얼라이저 종류"},
            "shorts": {"type": "boolean", "description": "세로 9:16 쇼츠 여부"},
            "clip_start": {"type": "string",
                           "description": "클립 시작 시각 'mm:ss' 또는 초. 전체면 빈 문자열"},
            "clip_len": {"type": "number", "description": "클립 길이(초)"},
            "kenburns": {"type": "boolean", "description": "배경 줌/팬 효과"},
            "title": {"type": "string", "description": "썸네일 제목"},
            "artist": {"type": "string", "description": "아티스트명"},
            "watermark": {"type": "string", "description": "우하단 워터마크 텍스트"},
        },
    },
}

EDIT_SYSTEM = """당신은 뮤직비디오 편집 어시스턴트입니다.
사용자의 자연어 요청을 받아 set_video_options 도구로 렌더 옵션을 변경합니다.

규칙:
- 바꿔야 하는 필드만 도구 입력에 넣으세요 (바뀌지 않는 값은 생략).
- 요청이 옵션 변경과 무관하면 도구를 호출하지 말고 짧게 안내만 하세요.
- 도구 호출 후에는 무엇을 어떻게 바꿨는지 한국어로 1~2문장으로 짧게 설명하세요."""


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
