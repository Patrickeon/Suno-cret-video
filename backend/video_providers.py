"""외부 AI 영상 생성 provider 추상화 (Phase 4).

프롬프트 -> AI 영상 클립(mp4) 생성. 생성된 클립은 make_mv.py 의 --video-bg 로
배경 트랙에 깔고, 그 위에 비주얼라이저/자막을 얹는다.

Kaiber / Higgsfield / Runway 등은 인증·엔드포인트가 제각각이라 공통 인터페이스로
감싸고, provider별 세부(엔드포인트/페이로드)는 각 클래스에서 채운다.

⚠️ 아래 Kaiber/Higgsfield 구현은 표준 흐름(submit->poll->download)을 갖춘
   **스텁**이다. 실제 API 키와 엔드포인트 사양을 받으면 표시된 TODO 를 채우면 된다.
"""
import os
import time
from abc import ABC, abstractmethod

try:
    import httpx
except ImportError:  # httpx 는 anthropic 의존성으로 보통 함께 설치됨
    httpx = None


class VideoProvider(ABC):
    """프롬프트로 영상 클립을 생성해 로컬 파일 경로로 반환하는 공통 인터페이스."""

    @abstractmethod
    def generate(self, prompt, out_path, duration=5, aspect="16:9", **opts):
        """영상 생성 후 out_path 에 저장하고 그 경로를 반환. 실패 시 예외."""
        raise NotImplementedError


class _PollingHTTPProvider(VideoProvider):
    """submit -> poll -> download 패턴 공통 구현. provider 는 세 훅만 채우면 됨."""

    def __init__(self, api_key=None, base_url=None, poll_interval=4, timeout=600):
        if httpx is None:
            raise RuntimeError("httpx 가 필요합니다: pip install httpx")
        self.api_key = api_key or os.environ.get(self.ENV_KEY)
        if not self.api_key:
            raise RuntimeError(f"{self.ENV_KEY} 가 설정되지 않았습니다.")
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.client = httpx.Client(timeout=30)

    # provider 별로 구현할 훅 ----------------------------------
    ENV_KEY = "VIDEO_PROVIDER_API_KEY"
    DEFAULT_BASE_URL = ""

    def _submit(self, prompt, duration, aspect, **opts):
        """생성 작업 제출 -> 외부 job id 반환."""
        raise NotImplementedError("provider별 _submit 구현 필요")

    def _poll(self, job_id):
        """(상태, 결과_url) 반환. 상태: 'pending'|'done'|'error'."""
        raise NotImplementedError("provider별 _poll 구현 필요")

    # 공통 흐름 ------------------------------------------------
    def generate(self, prompt, out_path, duration=5, aspect="16:9", **opts):
        job_id = self._submit(prompt, duration, aspect, **opts)
        waited = 0
        while waited < self.timeout:
            status, url = self._poll(job_id)
            if status == "done" and url:
                return self._download(url, out_path)
            if status == "error":
                raise RuntimeError(f"영상 생성 실패 (job {job_id})")
            time.sleep(self.poll_interval)
            waited += self.poll_interval
        raise TimeoutError(f"영상 생성 타임아웃 (job {job_id})")

    def _download(self, url, out_path):
        with self.client.stream("GET", url) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return out_path

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}


class ReplicateProvider(_PollingHTTPProvider):
    """Replicate — 문서화된 공개 API. 단일 토큰으로 여러 text-to-video 모델 사용.

    흐름: POST /v1/models/{model}/predictions -> 예측 id -> GET 으로 poll ->
    status=succeeded 면 output(영상 URL) 다운로드.
    모델은 REPLICATE_MODEL 환경변수 또는 생성 시 model= 인자로 교체 가능.
    """
    ENV_KEY = "REPLICATE_API_TOKEN"
    DEFAULT_BASE_URL = "https://api.replicate.com/v1"
    DEFAULT_MODEL = "minimax/video-01"  # text-to-video. 다른 모델로 교체 가능

    def __init__(self, api_key=None, base_url=None, model=None, **kw):
        super().__init__(api_key=api_key, base_url=base_url, **kw)
        self.model = model or os.environ.get("REPLICATE_MODEL", self.DEFAULT_MODEL)
        self._poll_url = None

    def _submit(self, prompt, duration, aspect, **opts):
        payload = {"input": {"prompt": prompt}}
        if aspect:
            payload["input"]["aspect_ratio"] = aspect  # 미지원 모델은 무시
        r = self.client.post(
            f"{self.base_url}/models/{self.model}/predictions",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        self._poll_url = (data.get("urls") or {}).get("get")
        return data["id"]

    def _poll(self, job_id):
        url = self._poll_url or f"{self.base_url}/predictions/{job_id}"
        r = self.client.get(url, headers=self._headers())
        r.raise_for_status()
        d = r.json()
        status = d.get("status")
        if status == "succeeded":
            out = d.get("output")
            if isinstance(out, list):
                out = out[-1] if out else None
            return ("done", out) if out else ("error", None)
        if status in ("failed", "canceled"):
            return "error", None
        return "pending", None


class KaiberProvider(_PollingHTTPProvider):
    ENV_KEY = "KAIBER_API_KEY"
    DEFAULT_BASE_URL = "https://api.kaiber.ai"  # TODO: 실제 베이스 URL 확인

    def _submit(self, prompt, duration, aspect, **opts):
        # TODO: 실제 Kaiber 생성 엔드포인트/페이로드로 교체
        raise NotImplementedError(
            "Kaiber API 사양(엔드포인트/페이로드)과 키를 받으면 여기서 작업을 제출하세요."
        )

    def _poll(self, job_id):
        raise NotImplementedError("Kaiber 상태 조회 엔드포인트로 교체")


class HiggsfieldProvider(_PollingHTTPProvider):
    ENV_KEY = "HIGGSFIELD_API_KEY"
    DEFAULT_BASE_URL = "https://api.higgsfield.ai"  # TODO: 실제 베이스 URL 확인

    def _submit(self, prompt, duration, aspect, **opts):
        raise NotImplementedError(
            "Higgsfield API 사양과 키를 받으면 여기서 작업을 제출하세요."
        )

    def _poll(self, job_id):
        raise NotImplementedError("Higgsfield 상태 조회 엔드포인트로 교체")


_PROVIDERS = {
    "replicate": ReplicateProvider,
    "kaiber": KaiberProvider,
    "higgsfield": HiggsfieldProvider,
}


def get_video_provider(name, **kwargs):
    name = (name or "").lower()
    if name not in _PROVIDERS:
        raise ValueError(
            f"unknown video provider: {name} (available: {list(_PROVIDERS)})"
        )
    return _PROVIDERS[name](**kwargs)
