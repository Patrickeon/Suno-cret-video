"""YouTube 직접 업로드 (OAuth).

⚠️ 외부 인증이 필요해 기본 의존성엔 없다. 사용하려면:
  1) Google Cloud 프로젝트에서 YouTube Data API v3 사용 설정
  2) OAuth 클라이언트(데스크톱 앱) 만들어 client_secret.json 다운로드 →
     backend/data/youtube_client_secret.json 로 저장
  3) pip install -r requirements-youtube.txt
  4) 최초 1회 인증:  python -m yt_upload  (브라우저 동의 → 토큰 저장)
그 후 /api/youtube/upload 로 업로드 가능.

토큰/시크릿은 backend/data/ (gitignore) 에 저장된다.
"""
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TOKEN_PATH = os.path.join(_DIR, "youtube_token.json")
CLIENT_SECRET = os.path.join(_DIR, "youtube_client_secret.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def auth_status():
    """UI 안내용: 토큰/시크릿 존재 여부."""
    return {
        "token": os.path.exists(TOKEN_PATH),
        "client_secret": os.path.exists(CLIENT_SECRET),
    }


def _load_credentials():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise RuntimeError(
            "구글 라이브러리가 필요합니다: pip install -r requirements-youtube.txt"
        ) from e
    if not os.path.exists(TOKEN_PATH):
        raise RuntimeError(
            "YouTube 인증 토큰이 없습니다. 최초 1회 'python -m yt_upload' 로 인증하세요."
        )
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def upload(video_path, title, description="", tags=None, privacy="private",
           made_for_kids=False):
    """영상 업로드 -> {video_id, url}. 실패 시 예외."""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as e:
        raise RuntimeError(
            "google-api-python-client 가 필요합니다: pip install -r requirements-youtube.txt"
        ) from e
    creds = _load_credentials()
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": (title or "제목 없음")[:100],
                    "description": description or "", "tags": tags or []},
        "status": {"privacyStatus": privacy or "private",
                   "selfDeclaredMadeForKids": bool(made_for_kids)},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True,
                            mimetype="video/mp4")
    resp = yt.videos().insert(part="snippet,status", body=body,
                              media_body=media).execute()
    return {"video_id": resp["id"], "url": f"https://youtu.be/{resp['id']}"}


def authorize():
    """최초 1회 로컬 OAuth 동의 흐름 실행 → 토큰 저장."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not os.path.exists(CLIENT_SECRET):
        raise SystemExit(f"클라이언트 시크릿이 없습니다: {CLIENT_SECRET}")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    creds = flow.run_local_server(port=0)
    os.makedirs(_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print(f"[done] 토큰 저장: {TOKEN_PATH}")


if __name__ == "__main__":
    authorize()
