"""AI 편집 에이전트 — provider 를 가짜로 주입해 tool_use→patch 추출 검증.
(실제 Anthropic API 호출 없음)"""
import json

import agent


class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeProvider:
    """chat() 호출 순서대로 미리 준 응답을 돌려준다."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def chat(self, system, messages, tools=None, max_tokens=2048):
        r = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return r


def test_tool_use_produces_patch(monkeypatch):
    tool = _Blk(type="tool_use", id="t1", name="set_video_options",
                input={"shorts": True, "viz": "spectrum"})
    final = _Resp([_Blk(type="text", text="쇼츠 + 스펙트럼으로 바꿨어요.")])
    fake = _FakeProvider([_Resp([tool]), final])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)

    reply, patch = agent.edit_video({"viz": "waves"}, "쇼츠로 스펙트럼", api_key="x")
    assert patch == {"shorts": True, "viz": "spectrum"}
    assert "스펙트럼" in reply
    assert fake.calls == 2  # tool 사용 후 후속 호출 1회


def test_no_tool_use_returns_empty_patch(monkeypatch):
    resp = _Resp([_Blk(type="text", text="옵션과 무관한 질문이에요.")])
    fake = _FakeProvider([resp])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)

    reply, patch = agent.edit_video({}, "안녕?", api_key="x")
    assert patch == {}
    assert reply
    assert fake.calls == 1


def test_edit_tool_schema_has_new_fields():
    props = agent.EDIT_TOOL["input_schema"]["properties"]
    for k in ("viz", "shorts", "bg_color", "align", "intro", "outro"):
        assert k in props


def test_get_provider_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        agent.get_provider("nope")


def test_generate_metadata(monkeypatch):
    md = {"title": "여름밤 발라드", "description": "감성 가사 영상 #발라드",
          "tags": ["발라드", "가사"], "chapters": []}
    tool = _Blk(type="tool_use", id="m1", name="set_youtube_metadata", input=md)
    fake = _FakeProvider([_Resp([tool])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    out = agent.generate_metadata("곡", "아티스트", "가사 줄들", api_key="x")
    assert out["title"] == "여름밤 발라드"
    assert "발라드" in out["tags"]


def test_translate_lyrics(monkeypatch):
    tool = _Blk(type="tool_use", id="t", name="set_translation",
                input={"lines": ["Starlight", "Your voice"]})
    fake = _FakeProvider([_Resp([tool])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    out = agent.translate_lyrics(["별빛", "너의 목소리"], target="영어", api_key="x")
    assert out == ["Starlight", "Your voice"]


def test_translate_lyrics_length_padded(monkeypatch):
    # 번역 줄이 부족하면 원문 길이에 맞춰 패딩
    tool = _Blk(type="tool_use", id="t", name="set_translation", input={"lines": ["A"]})
    fake = _FakeProvider([_Resp([tool])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    out = agent.translate_lyrics(["가", "나", "다"], api_key="x")
    assert len(out) == 3


def test_generate_metadata_no_tool_returns_empty(monkeypatch):
    fake = _FakeProvider([_Resp([_Blk(type="text", text="음...")])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    assert agent.generate_metadata("곡", "a", "가사", api_key="x") == {}


def test_suggest_palette(monkeypatch):
    pal = {"viz_color": "FDA4AF,F9A8D4", "bg_grad": "1A0F1E,2D1B3A,12212E",
           "viz": "waves", "mood": "몽환적"}
    tool = _Blk(type="tool_use", id="p1", name="set_palette", input=pal)
    fake = _FakeProvider([_Resp([tool])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    out = agent.suggest_palette("달빛 산책", "별빛이 흐르는 밤", api_key="x")
    assert out["viz_color"] == "FDA4AF,F9A8D4"
    assert out["mood"] == "몽환적"


def test_edit_tool_schema_has_design_fields():
    props = agent.EDIT_TOOL["input_schema"]["properties"]
    for k in ("viz_color", "bg_style", "bg_grad", "disc", "progress_bar", "sub_preview"):
        assert k in props


def test_generate_album_cover_prompt(monkeypatch):
    tool = _Blk(type="tool_use", id="c1", name="set_album_cover_prompt",
                input={"prompt": "dreamy pastel synthwave sunset, vinyl album cover, "
                                 "no text, no typography, no watermark"})
    fake = _FakeProvider([_Resp([tool])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    out = agent.generate_album_cover_prompt("여름밤 드라이브", "밤바람이 부는 도로 위", api_key="x")
    assert out.startswith("dreamy pastel synthwave sunset")
    assert "no text" in out


def test_generate_album_cover_prompt_no_tool_returns_empty(monkeypatch):
    fake = _FakeProvider([_Resp([_Blk(type="text", text="음...")])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    assert agent.generate_album_cover_prompt("t", "l", api_key="x") == ""


def test_generate_storyboard(monkeypatch):
    scenes = [{"prompt": "misty dawn city, cinematic, no text", "label": "도입"},
              {"prompt": "neon rain street, cinematic, no text", "label": "후렴"}]
    tool = _Blk(type="tool_use", id="s1", name="set_storyboard",
                input={"scenes": scenes, "style": "cinematic"})
    fake = _FakeProvider([_Resp([tool])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    out = agent.generate_storyboard("선", "가사...", n_scenes=2, api_key="x")
    assert len(out) == 2 and out[0]["prompt"].startswith("misty")


def test_generate_storyboard_no_tool_empty(monkeypatch):
    fake = _FakeProvider([_Resp([_Blk(type="text", text="...")])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    assert agent.generate_storyboard("t", "l", api_key="x") == []


# ─────────────────────────────────────────────────────────────
# claude CLI provider (API 키 불필요, 로컬 `claude` CLI 호출)
# ─────────────────────────────────────────────────────────────

class _FakeCompletedProcess:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_get_provider_claude_cli_returns_instance():
    provider = agent.get_provider("claude-cli")
    assert isinstance(provider, agent.ClaudeCLIProvider)


def test_claude_cli_chat_text_response(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return _FakeCompletedProcess(
            stdout=json.dumps({"result": "hello", "is_error": False}),
            returncode=0,
        )

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    provider = agent.ClaudeCLIProvider()
    resp = provider.chat("system prompt", [{"role": "user", "content": "hi"}])
    assert resp.content[0].type == "text"
    assert resp.content[0].text == "hello"
    assert "--json-schema" not in calls["cmd"]


def test_claude_cli_chat_tool_use_response(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return _FakeCompletedProcess(
            stdout=json.dumps({"structured_output": {"disc": True}, "is_error": False}),
            returncode=0,
        )

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    provider = agent.ClaudeCLIProvider()
    resp = provider.chat("system prompt", [{"role": "user", "content": "record mode"}],
                         tools=[agent.EDIT_TOOL])
    block = resp.content[0]
    assert block.type == "tool_use"
    assert block.name == agent.EDIT_TOOL["name"]
    assert block.input == {"disc": True}
    assert "--json-schema" in calls["cmd"]
    idx = calls["cmd"].index("--json-schema")
    assert json.loads(calls["cmd"][idx + 1]) == agent.EDIT_TOOL["input_schema"]


def test_claude_cli_chat_nonzero_returncode_raises(monkeypatch):
    def fake_run(cmd, **kwargs):
        return _FakeCompletedProcess(stdout="", returncode=1, stderr="boom")

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    provider = agent.ClaudeCLIProvider()
    import pytest
    with pytest.raises(RuntimeError):
        provider.chat("sys", [{"role": "user", "content": "hi"}])


def test_claude_cli_chat_is_error_raises(monkeypatch):
    def fake_run(cmd, **kwargs):
        return _FakeCompletedProcess(
            stdout=json.dumps({"result": "boom", "is_error": True}),
            returncode=0,
        )

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    provider = agent.ClaudeCLIProvider()
    import pytest
    with pytest.raises(RuntimeError):
        provider.chat("sys", [{"role": "user", "content": "hi"}])


def test_content_to_text_plain_string():
    assert agent._content_to_text("hello") == "hello"


def test_content_to_text_text_blocks():
    out = agent._content_to_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
    assert out == "a\nb"


def test_content_to_text_tool_use_and_result_blocks():
    content = [
        {"type": "tool_use", "name": "set_video_options", "input": {"shorts": True}},
        {"type": "tool_result", "tool_use_id": "t1", "content": "적용됨"},
    ]
    out = agent._content_to_text(content)
    assert "set_video_options" in out
    assert "적용됨" in out


def test_flatten_messages_mixed_shapes():
    messages = [
        {"role": "user", "content": "plain text"},
        {"role": "assistant", "content": [{"type": "text", "text": "reply"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    ]
    out = agent._flatten_messages(messages)
    assert "plain text" in out
    assert "reply" in out
    assert "ok" in out


def test_settings_default_llm_provider_is_claude():
    # claude-cli 는 실제 통합 테스트에서 신뢰도 문제가 확인돼 기본값이 아니다 —
    # provider 선택지로는 남아있다 (get_provider("claude-cli") 는 여전히 동작).
    import settings
    assert settings.DEFAULTS["llm_provider"] == "claude"
