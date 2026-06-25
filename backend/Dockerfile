# 백엔드: FastAPI + make_mv.py(ffmpeg) — Cloud Run 용
# 빌드 컨텍스트는 repo 루트여야 함 (make_mv.py 가 backend 상위에 있으므로):
#   docker build -f backend/Dockerfile -t suno-backend .
FROM python:3.11-slim

# ffmpeg + 한글 폰트(NanumGothic) 설치
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg fonts-nanum fonts-nanum-coding \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 (레이어 캐시)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# 렌더 엔진 + 백엔드 코드
COPY make_mv.py ./make_mv.py
COPY backend/ ./backend/

# Linux 컨테이너에는 Malgun Gothic 이 없으므로 NanumGothic 사용
ENV MV_FONT="NanumGothic"
ENV PORT=8080

WORKDIR /app/backend
# Cloud Run 은 $PORT 로 트래픽을 보냄
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
