# ☁️ GCP 배포 가이드 (Cloud Run)

백엔드(FastAPI+ffmpeg)와 프론트(Next.js)를 각각 Cloud Run 서비스로 배포한다.

```
[브라우저] → 프론트(Cloud Run) → 백엔드(Cloud Run, ffmpeg 렌더 + AI 에이전트)
```

## 배포 전 로컬 검증 (Docker Compose)

프로덕션과 동일한 컨테이너로 먼저 로컬에서 띄워 확인:

```bash
docker compose up --build
# 백엔드 http://localhost:8000 , 프론트 http://localhost:3000
```

이게 정상 동작하면 같은 이미지가 Cloud Run 에서도 동작한다.

## 원클릭 배포 (스크립트)

백엔드→URL확보→프론트(백엔드 URL 주입)→CORS 좁히기까지 자동:

```powershell
# Windows
$env:ANTHROPIC_API_KEY="sk-ant-..."   # (선택)
$env:GCS_BUCKET="my-bucket"           # (선택) 결과물 영속화
./deploy.ps1 -Project my-gcp-project
```
```bash
# macOS/Linux
export ANTHROPIC_API_KEY=sk-ant-...   # (선택)
export GCS_BUCKET=my-bucket           # (선택)
PROJECT=my-gcp-project ./deploy.sh
```

> `gcloud` + Docker 가 있는 환경에서 실행. (이 저장소의 Docker 이미지 빌드는 검증 완료)

## CI 빌드 (Cloud Build)

이미지 빌드+푸시는 `cloudbuild.yaml` 로:

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=asia-northeast3,_REPO=suno,_BACKEND_URL=https://<백엔드-URL>
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

1. **결과물(out.mp4/썸네일) 영속성** — Cloud Run 디스크는 임시.
   - **해결됨(선택)**: `GCS_BUCKET` 환경변수를 주면 `storage.py` 가 결과를 GCS 에 저장·스트리밍.
2. **잡 메타데이터** — `jobs.py` 가 디스크(job.json)에 저장하나 인스턴스 간 공유는 안 됨.
   - 단일 인스턴스(`--max-instances 1`, 배포 스크립트 기본값)면 OK.
   - 멀티 인스턴스로 키우려면 메타를 **Firestore/GCS** 로 이전 (`jobs.py` 가 교체 지점).
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
