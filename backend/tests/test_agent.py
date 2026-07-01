"""AI 편집 에이전트 — provider 를 가짜로 주입해 tool_use→patch 추출 검증.
(실제 Anthropic API 호출 없음)"""
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


def test_generate_metadata_no_tool_returns_empty(monkeypatch):
    fake = _FakeProvider([_Resp([_Blk(type="text", text="음...")])])
    monkeypatch.setattr(agent, "get_provider", lambda *a, **k: fake)
    assert agent.generate_metadata("곡", "a", "가사", api_key="x") == {}
