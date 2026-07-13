"""앱 토큰 미들웨어 (APP_TOKEN) 테스트."""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def test_no_token_configured_allows_all(monkeypatch):
    monkeypatch.setattr(main, "APP_TOKEN", "")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/fonts").status_code == 200


def test_token_required_when_configured(monkeypatch):
    monkeypatch.setattr(main, "APP_TOKEN", "sekrit")
    r = client.get("/api/fonts")
    assert r.status_code == 401
    assert client.get("/api/fonts", headers={"X-App-Token": "wrong"}).status_code == 401


def test_token_accepted_via_header_and_query(monkeypatch):
    monkeypatch.setattr(main, "APP_TOKEN", "sekrit")
    assert client.get("/api/fonts", headers={"X-App-Token": "sekrit"}).status_code == 200
    # <video>/<img>/<a download> 용 쿼리 방식
    assert client.get("/api/fonts", params={"token": "sekrit"}).status_code == 200


def test_health_exempt(monkeypatch):
    monkeypatch.setattr(main, "APP_TOKEN", "sekrit")
    assert client.get("/api/health").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_non_ascii_token_rejected_not_500(monkeypatch):
    monkeypatch.setattr(main, "APP_TOKEN", "sekrit")
    assert client.get("/api/fonts", params={"token": "한글토큰"}).status_code == 401
