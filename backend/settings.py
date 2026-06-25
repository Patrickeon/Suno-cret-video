"""런타임 설정 스토어 (BYOK — Bring Your Own Key).

사용자가 UI에서 LLM/영상 provider 와 API 키를 직접 넣고 그때그때 교체할 수 있게 한다.
키는 로컬 파일(backend/data/settings.json, gitignore 대상)에 저장된다.

⚠️ 로컬 개발용 평문 저장이다. 프로덕션에서는 Secret Manager 등으로 교체할 것.
공개 응답(get_public)은 절대 원본 키를 내보내지 않고 설정 여부(bool)만 반환한다.
"""
import json
import os
import threading

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_PATH = os.path.join(_DIR, "settings.json")
_LOCK = threading.Lock()

DEFAULTS = {
    "llm_provider": "claude",
    "llm_model": "claude-sonnet-4-6",
    "llm_api_key": "",
    "video_provider": "kaiber",
    "video_api_key": "",
}

# 환경변수 폴백 (UI에 키가 없으면 사용)
_ENV_FALLBACK = {
    "llm_api_key": "ANTHROPIC_API_KEY",
    "video_api_key": "KAIBER_API_KEY",
}

_state = None


def _load():
    global _state
    if _state is not None:
        return _state
    data = dict(DEFAULTS)
    if os.path.exists(_PATH):
        try:
            with open(_PATH, encoding="utf-8") as f:
                data.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
    _state = data
    return _state


def _persist():
    os.makedirs(_DIR, exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)


def update(patch: dict):
    """제공된 필드만 갱신. *_api_key 는 빈 문자열이면 무시(기존 키 유지)."""
    with _LOCK:
        s = _load()
        for k, v in patch.items():
            if k not in DEFAULTS or v is None:
                continue
            if k.endswith("_api_key") and v == "":
                continue  # 빈 값으로 키를 지우지 않음
            s[k] = v
        _persist()
    return get_public()


def get_raw():
    with _LOCK:
        return dict(_load())


def get_key(field: str) -> str:
    """UI 설정 키 우선, 없으면 환경변수 폴백."""
    s = _load()
    return s.get(field) or os.environ.get(_ENV_FALLBACK.get(field, ""), "")


def get_public() -> dict:
    """키 원본은 빼고 설정 여부만 반환."""
    s = _load()
    return {
        "llm_provider": s["llm_provider"],
        "llm_model": s["llm_model"],
        "llm_key_set": bool(get_key("llm_api_key")),
        "video_provider": s["video_provider"],
        "video_key_set": bool(get_key("video_api_key")),
    }
