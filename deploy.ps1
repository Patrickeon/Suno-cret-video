# Cloud Run 2단계 배포 (Windows PowerShell)
#
# 사전: gcloud 설치+로그인, Docker Desktop 실행, Artifact Registry 저장소 생성(DEPLOY.md 0단계)
# 사용 예:
#   $env:ANTHROPIC_API_KEY="sk-ant-..."   # (선택) AI 편집용
#   $env:GCS_BUCKET="my-bucket"           # (선택) 결과물 영속화
#   ./deploy.ps1 -Project my-gcp-project
param(
  [string]$Project = "",
  [string]$Region = "asia-northeast3",
  [string]$Repo = "suno"
)

$ErrorActionPreference = "Stop"
if (-not $Project) { $Project = (gcloud config get-value project) }
$Reg = "$Region-docker.pkg.dev/$Project/$Repo"

Write-Host "▶ Project=$Project Region=$Region Repo=$Repo"
gcloud auth configure-docker "$Region-docker.pkg.dev" --quiet

# 1) 백엔드 (컨텍스트=루트, make_mv.py 포함)
Write-Host "▶ 백엔드 빌드/푸시"
docker build -f backend/Dockerfile -t "$Reg/backend" .
docker push "$Reg/backend"

$envVars = @("ALLOWED_ORIGINS=*")
if ($env:ANTHROPIC_API_KEY) { $envVars += "ANTHROPIC_API_KEY=$($env:ANTHROPIC_API_KEY)" }
if ($env:GCS_BUCKET) { $envVars += "GCS_BUCKET=$($env:GCS_BUCKET)" }
$envArg = ($envVars -join ",")

Write-Host "▶ 백엔드 배포"
gcloud run deploy suno-backend --image "$Reg/backend" --region $Region `
  --allow-unauthenticated --memory 2Gi --cpu 2 --timeout 600 --max-instances 1 `
  --set-env-vars $envArg

$BackendUrl = (gcloud run services describe suno-backend --region $Region --format="value(status.url)")
Write-Host "▶ Backend URL: $BackendUrl"

# 2) 프론트 (백엔드 URL 을 빌드타임에 주입)
Write-Host "▶ 프론트 빌드/푸시"
docker build -f frontend/Dockerfile --build-arg "NEXT_PUBLIC_API_BASE=$BackendUrl" -t "$Reg/frontend" frontend
docker push "$Reg/frontend"

Write-Host "▶ 프론트 배포"
gcloud run deploy suno-frontend --image "$Reg/frontend" --region $Region --allow-unauthenticated

$FrontUrl = (gcloud run services describe suno-frontend --region $Region --format="value(status.url)")

# 3) 백엔드 CORS 를 실제 프론트 도메인으로 좁히기
Write-Host "▶ 백엔드 CORS 갱신: $FrontUrl"
$envVars[0] = "ALLOWED_ORIGINS=$FrontUrl"
gcloud run services update suno-backend --region $Region --set-env-vars ($envVars -join ",")

Write-Host "`n✅ 완료"
Write-Host "  프론트: $FrontUrl"
Write-Host "  백엔드: $BackendUrl"
Write-Host "  (키는 --set-secrets 로 Secret Manager 사용 권장 — DEPLOY.md 참고)"
