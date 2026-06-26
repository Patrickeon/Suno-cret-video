"""출력물 스토리지 추상화.

Cloud Run 의 로컬 디스크는 임시(ephemeral)라, 렌더 결과(out.mp4/썸네일)를 그대로 두면
인스턴스 재시작·재배포 시 사라진다. GCS_BUCKET 환경변수를 주면 결과를 GCS 에 저장·스트리밍한다.

- 기본: LocalStorage (개발/단일 인스턴스) — job_dir 의 파일을 그대로 서빙
- GCS_BUCKET 설정 시: GcsStorage — 렌더 후 업로드, 서빙은 GCS 에서 스트리밍

ffmpeg 는 로컬 파일에 써야 하므로 렌더는 항상 로컬 job_dir 에서 수행하고,
끝난 뒤 save_outputs() 로 저장소에 올린다.
"""
import os
from abc import ABC, abstractmethod

from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

_MEDIA = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _media_type(name):
    return _MEDIA.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


class Storage(ABC):
    @abstractmethod
    def save_outputs(self, job_id, job_dir, names):
        """렌더 완료된 산출물(names)을 저장소로 반영."""

    @abstractmethod
    def serve(self, job_id, job_dir, name, download_name):
        """FastAPI Response 로 산출물 서빙. 없으면 404."""


class LocalStorage(Storage):
    def save_outputs(self, job_id, job_dir, names):
        pass  # 이미 로컬 job_dir 에 있음

    def serve(self, job_id, job_dir, name, download_name):
        path = os.path.join(job_dir, name)
        if not os.path.exists(path):
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(path, media_type=_media_type(name), filename=download_name)


class GcsStorage(Storage):
    """GCS 백엔드. google-cloud-storage 필요 (Dockerfile/requirements 에 포함)."""

    def __init__(self, bucket):
        from google.cloud import storage  # lazy: 로컬 기본 경로에선 불필요
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    def _blob(self, job_id, name):
        return self._bucket.blob(f"jobs/{job_id}/{name}")

    def save_outputs(self, job_id, job_dir, names):
        for name in names:
            path = os.path.join(job_dir, name)
            if os.path.exists(path):
                self._blob(job_id, name).upload_from_filename(path)

    def serve(self, job_id, job_dir, name, download_name):
        blob = self._blob(job_id, name)
        if not blob.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        stream = blob.open("rb")
        return StreamingResponse(
            stream,
            media_type=_media_type(name),
            headers={"Content-Disposition": f'inline; filename="{download_name}"'},
        )


def get_storage():
    bucket = os.environ.get("GCS_BUCKET")
    if bucket:
        return GcsStorage(bucket)
    return LocalStorage()
