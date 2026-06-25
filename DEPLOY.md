# ☁️ GCP 배포 가이드 (Cloud Run)

백엔드(FastAPI+ffmpeg)와 프론트(Next.js)를 각각 Cloud Run 서비스로 배포한다.

```
[브라우저] → 프론트(Cloud Run) → 백엔드(Cloud Run, ffmpeg 렌더 + AI 에이전트)
```

## 0. 사전 준비

```bash
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

# 이미지 저장소(Artifact Registry) 1회 생성
gcloud artifacts repositories create suno --repository-format=docker --location=asia-northeast3
```

(리전 예: `asia-northeast3` = 서울)

## 1. 백엔드 배포

> 빌드 컨텍스트는 **repo 루트** (make_mv.py 가 backend 상위에 있으므로).

```bash
REGION=asia-northeast3
REPO=asia-northeast3-docker.pkg.dev/<YOUR_PROJECT_ID>/suno

# 빌드 & 푸시 (Cloud Build 사용 — 로컬 docker 불필요)
gcloud builds submit --tag $REPO/backend --gcs-log-dir=gs://<bucket>/logs \
  --substitutions=_X=_ . -f backend/Dockerfile   # 또는 로컬: docker build -f backend/Dockerfile -t $REPO/backend . && docker push $REPO/backend

# 배포
gcloud run deploy suno-backend \
  --image $REPO/backend \
  --region $REGION \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 600 \
  --set-env-vars "ANTHROPIC_API_KEY=sk-ant-...,ALLOWED_ORIGINS=https://<프론트-URL>"
```

- `--memory 2Gi --cpu 2` : ffmpeg 렌더가 CPU/메모리를 쓰므로 넉넉히.
- `--timeout 600` : 긴 곡 렌더 대비.
- 배포 후 출력되는 **백엔드 URL** 을 프론트 빌드에 사용.

## 2. 프론트엔드 배포

> 클라이언트 번들에 백엔드 주소가 **빌드타임**에 박히므로, 1단계 백엔드 URL 을 넘긴다.

```bash
BACKEND_URL=https://suno-backend-xxxx.a.run.app

# 로컬 docker 빌드 예시 (frontend/ 컨텍스트)
docker build -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE=$BACKEND_URL \
  -t $REPO/frontend frontend
docker push $REPO/frontend

gcloud run deploy suno-frontend \
  --image $REPO/frontend --region $REGION --allow-unauthenticated
```

배포 후 프론트 URL 을 백엔드의 `ALLOWED_ORIGINS` 에 넣어 재배포(또는 처음부터 지정).

## ⚠️ 운영 시 반드시 고려할 것 (현재 골격의 한계)

1. **파일시스템이 임시(ephemeral)** — Cloud Run 인스턴스의 디스크는 재시작 시 사라지고,
   인스턴스가 여러 개면 잡이 공유되지 않는다.
   - 임시 해결: `--min-instances 1 --max-instances 1` 로 단일 인스턴스 운영.
   - 제대로: **잡/결과를 Cloud Storage(GCS)** 에 저장하도록 `jobs.py`/서빙 경로 교체.
2. **인메모리 잡 스토어** — 위와 같은 이유로 재시작 시 잡 정보 소실 → DB(Firestore 등)나 GCS 메타로 이전.
3. **렌더는 동기 백그라운드 스레드** — 부하가 커지면 **Cloud Tasks + 별도 워커**로 분리 권장.
4. **API 키 보안** — `ANTHROPIC_API_KEY` 등은 **Secret Manager** 사용 권장
   (`--set-secrets ANTHROPIC_API_KEY=anthropic-key:latest`).
5. **한글 폰트** — 백엔드 이미지는 `fonts-nanum` 설치 + `MV_FONT=NanumGothic` 로 처리됨.
6. **CORS** — 백엔드 `ALLOWED_ORIGINS` 에 실제 프론트 도메인 지정.

## 다음 단계 (운영화)

- [ ] `jobs.py` → GCS 기반 잡/자산 저장으로 교체
- [ ] 렌더 큐를 Cloud Tasks 로 분리
- [ ] Secret Manager 로 키 관리
- [ ] 로그인/멀티유저 (Firebase Auth 등)
