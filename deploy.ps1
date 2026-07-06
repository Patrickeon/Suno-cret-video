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

# 네이티브 도구(gcloud/docker)는 성공해도 stderr 에 경고를 찍는 경우가 흔하다.
# ErrorActionPreference=Stop 이면 그런 경고까지 종료 에러로 취급해 스크립트가
# 죽으므로, 대신 각 필수 단계 뒤에 $LASTEXITCODE 를 명시적으로 검사한다.
$ErrorActionPreference = "Continue"

function Invoke-Checked($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what 실패 (exit $LASTEXITCODE)" }
}

if (-not $Project) { $Project = (gcloud config get-value project 2>$null) }
$Reg = "$Region-docker.pkg.dev/$Project/$Repo"

Write-Host "▶ Project=$Project Region=$Region Repo=$Repo"
gcloud auth configure-docker "$Region-docker.pkg.dev" --quiet 2>&1 | Write-Host
Invoke-Checked "docker 인증 설정"

# 1) 백엔드 (컨텍스트=루트, make_mv.py 포함)
Write-Host "▶ 백엔드 빌드/푸시"
docker build -f backend/Dockerfile -t "$Reg/backend" . 2>&1 | Write-Host
Invoke-Checked "백엔드 이미지 빌드"
docker push "$Reg/backend" 2>&1 | Write-Host
Invoke-Checked "백엔드 이미지 푸시"

$envVars = @("ALLOWED_ORIGINS=*")
if ($env:ANTHROPIC_API_KEY) { $envVars += "ANTHROPIC_API_KEY=$($env:ANTHROPIC_API_KEY)" }
if ($env:GCS_BUCKET) { $envVars += "GCS_BUCKET=$($env:GCS_BUCKET)" }
$envArg = ($envVars -join ",")

Write-Host "▶ 백엔드 배포"
gcloud run deploy suno-backend --image "$Reg/backend" --region $Region `
  --allow-unauthenticated --memory 2Gi --cpu 2 --timeout 600 --max-instances 1 `
  --set-env-vars $envArg 2>&1 | Write-Host
Invoke-Checked "백엔드 Cloud Run 배포"

$BackendUrl = (gcloud run services describe suno-backend --region $Region --format="value(status.url)" 2>$null)
Write-Host "▶ Backend URL: $BackendUrl"

# 2) 프론트 (백엔드 URL 을 빌드타임에 주입)
Write-Host "▶ 프론트 빌드/푸시"
docker build -f frontend/Dockerfile --build-arg "NEXT_PUBLIC_API_BASE=$BackendUrl" -t "$Reg/frontend" frontend 2>&1 | Write-Host
Invoke-Checked "프론트 이미지 빌드"
docker push "$Reg/frontend" 2>&1 | Write-Host
Invoke-Checked "프론트 이미지 푸시"

Write-Host "▶ 프론트 배포"
gcloud run deploy suno-frontend --image "$Reg/frontend" --region $Region --allow-unauthenticated 2>&1 | Write-Host
Invoke-Checked "프론트 Cloud Run 배포"

$FrontUrl = (gcloud run services describe suno-frontend --region $Region --format="value(status.url)" 2>$null)

# 3) 백엔드 CORS 를 실제 프론트 도메인으로 좁히기
Write-Host "▶ 백엔드 CORS 갱신: $FrontUrl"
$envVars[0] = "ALLOWED_ORIGINS=$FrontUrl"
gcloud run services update suno-backend --region $Region --set-env-vars ($envVars -join ",") 2>&1 | Write-Host
Invoke-Checked "백엔드 CORS 갱신"

Write-Host "`n✅ 완료"
Write-Host "  프론트: $FrontUrl"
Write-Host "  백엔드: $BackendUrl"
Write-Host "  (키는 --set-secrets 로 Secret Manager 사용 권장 — DEPLOY.md 참고)"
