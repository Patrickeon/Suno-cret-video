#!/usr/bin/env bash
# Cloud Run 2단계 배포 (macOS/Linux)
#
# 사전: gcloud 로그인, Docker 실행, Artifact Registry 저장소 생성(DEPLOY.md 0단계)
# 사용 예:
#   export ANTHROPIC_API_KEY=sk-ant-...   # (선택)
#   export GCS_BUCKET=my-bucket           # (선택) 결과물 영속화
#   PROJECT=my-gcp-project ./deploy.sh
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project)}"
REGION="${REGION:-asia-northeast3}"
REPO="${REPO:-suno}"
REG="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

echo "▶ Project=$PROJECT Region=$REGION Repo=$REPO"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# 1) 백엔드 (컨텍스트=루트)
echo "▶ 백엔드 빌드/푸시"
docker build -f backend/Dockerfile -t "${REG}/backend" .
docker push "${REG}/backend"

ENVV="ALLOWED_ORIGINS=*"
[ -n "${ANTHROPIC_API_KEY:-}" ] && ENVV="${ENVV},ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
[ -n "${GCS_BUCKET:-}" ] && ENVV="${ENVV},GCS_BUCKET=${GCS_BUCKET}"

# 접속 토큰: 미지정 시 자동 생성. 백엔드 API 전체가 이 토큰을 요구한다
# (프론트 첫 접속 때 입력). 재배포 시 기존 토큰을 유지하려면 APP_TOKEN 지정.
if [ -z "${APP_TOKEN:-}" ]; then
  APP_TOKEN=$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')
  echo "▶ APP_TOKEN 자동 생성됨 (재배포 시 유지하려면 APP_TOKEN 환경변수로 지정)"
fi
ENVV="${ENVV},APP_TOKEN=${APP_TOKEN}"

echo "▶ 백엔드 배포"
gcloud run deploy suno-backend --image "${REG}/backend" --region "${REGION}" \
  --allow-unauthenticated --memory 2Gi --cpu 2 --timeout 600 --max-instances 1 \
  --set-env-vars "${ENVV}"

BACKEND_URL=$(gcloud run services describe suno-backend --region "${REGION}" --format='value(status.url)')
echo "▶ Backend URL: ${BACKEND_URL}"

# 2) 프론트 (백엔드 URL 주입)
echo "▶ 프론트 빌드/푸시"
docker build -f frontend/Dockerfile --build-arg "NEXT_PUBLIC_API_BASE=${BACKEND_URL}" -t "${REG}/frontend" frontend
docker push "${REG}/frontend"

echo "▶ 프론트 배포"
gcloud run deploy suno-frontend --image "${REG}/frontend" --region "${REGION}" --allow-unauthenticated
FRONT_URL=$(gcloud run services describe suno-frontend --region "${REGION}" --format='value(status.url)')

# 3) 백엔드 CORS 좁히기
echo "▶ 백엔드 CORS 갱신: ${FRONT_URL}"
gcloud run services update suno-backend --region "${REGION}" \
  --set-env-vars "$(echo "${ENVV}" | sed "s#ALLOWED_ORIGINS=\*#ALLOWED_ORIGINS=${FRONT_URL}#")"

echo ""
echo "✅ 완료"
echo "  프론트: ${FRONT_URL}"
echo "  백엔드: ${BACKEND_URL}"
echo "  접속 토큰(APP_TOKEN): ${APP_TOKEN}  ← 프론트 첫 접속 시 입력"
