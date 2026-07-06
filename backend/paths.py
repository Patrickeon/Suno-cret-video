"""로컬 실행 시 잡/설정 데이터를 저장할 위치.

로컬(데스크톱) 실행과 GCP(컨테이너) 배포의 설정을 분리한다:
  - 로컬: MV_DATA_DIR 환경변수로 원하는 경로 지정 가능. 지정하지 않으면
    사용자 "문서" 폴더 아래 'Suno MV Studio' 폴더를 기본값으로 만들어 쓴다.
  - GCP: backend/Dockerfile·docker-compose.yml 이 MV_DATA_DIR 을 컨테이너 내부
    경로(/app/backend/data)로 명시적으로 고정한다 — 결과물 영속화는 이 경로와
    무관하게 GCS_BUCKET 이 따로 처리한다(storage.py). 즉 이 파일의 "문서 폴더"
    기본값은 컨테이너에서는 절대 쓰이지 않는다.
"""
import os


def _documents_dir():
    """OS 별 '문서' 폴더 경로. Windows 는 사용자가 다른 드라이브로 옮긴
    경우까지 반영하기 위해 셸 API(SHGetFolderPath)를 우선 사용한다."""
    if os.name == "nt":
        try:
            import ctypes
            CSIDL_PERSONAL = 5       # My Documents
            SHGFP_TYPE_CURRENT = 0
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(
                0, CSIDL_PERSONAL, 0, SHGFP_TYPE_CURRENT, buf)
            if buf.value:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def data_dir():
    """잡/설정 데이터 루트 디렉터리 (없으면 생성). MV_DATA_DIR 로 재정의 가능."""
    d = os.environ.get("MV_DATA_DIR") or os.path.join(
        _documents_dir(), "Suno MV Studio")
    os.makedirs(d, exist_ok=True)
    return d
