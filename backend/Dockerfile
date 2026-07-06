# 백엔드: FastAPI + make_mv.py(ffmpeg) — Cloud Run 용
# 빌드 컨텍스트는 repo 루트여야 함 (make_mv.py 가 backend 상위에 있으므로):
#   docker build -f backend/Dockerfile -t suno-backend .
FROM python:3.11-slim

# ffmpeg + 한글 폰트(NanumGothic) 설치
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg fonts-nanum \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 (레이어 캐시)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# 렌더 엔진 + 동봉 폰트 + 백엔드 코드
COPY make_mv.py ./make_mv.py
COPY fonts/ ./fonts/
COPY backend/ ./backend/
ENV PORT=8080
# 컨테이너 전용 로컬 데이터 경로 — 로컬 데스크톱 실행의 "문서 폴더" 기본값이
# 컨테이너에선 절대 적용되지 않도록 명시적으로 고정한다(paths.py 참고).
# 결과물 영속화는 이 경로와 무관하게 GCS_BUCKET 이 따로 처리한다.
ENV MV_DATA_DIR=/app/backend/data

WORKDIR /app/backend
# Cloud Run 은 $PORT 로 트래픽을 보냄
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
