param(
    [string]$Message = "",
    [switch]$Direct,   # SSH directly to server (skip GitHub Actions, deploy now)
    [switch]$Restart   # Just restart Docker containers on server, no code changes
)

$SSH_HOST = "20.164.200.242"
$SSH_USER = "azureuser"
$SSH_KEY  = "$env:USERPROFILE\.ssh\id_ed25519"

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    OK: $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "    !! $Text" -ForegroundColor Yellow }
function Write-Err  { param([string]$Text) Write-Host "`nERROR: $Text" -ForegroundColor Red }

function Invoke-SSH {
    param([string]$Script)
    & ssh -i $SSH_KEY -o StrictHostKeyChecking=no "${SSH_USER}@${SSH_HOST}" $Script
    return $LASTEXITCODE
}

try {

    # ── RESTART ONLY ──────────────────────────────────────────────────────────
    if ($Restart) {
        Write-Step "Restarting SibanyeTrack containers on $SSH_HOST"
        $code = Invoke-SSH @'
set -e
cd ~/sibanyetrack
echo "--- Container status before restart ---"
docker ps --filter name=sibanyetrack --format "table {{.Names}}\t{{.Status}}"
docker rm -f sibanyetrack-web-1 2>/dev/null || true
docker compose -f docker-compose.prod.yml up -d --no-deps web
echo "--- Container status after restart ---"
docker ps --filter name=sibanyetrack --format "table {{.Names}}\t{{.Status}}"
'@
        if ($code -ne 0) { throw "Restart failed (exit $code)" }
        Write-Ok "Containers restarted"
        Write-Host ""
        Read-Host "Press Enter to close"
        exit 0
    }

    # ── COMMIT + PUSH ─────────────────────────────────────────────────────────
    Write-Step "Checking for local changes"
    $status = & git status --porcelain 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git status failed: $status" }

    if ($status) {
        if ($Message -eq "") {
            $Message = Read-Host "Commit message"
            if ($Message -eq "") { throw "Commit message cannot be empty" }
        }
        & git add -A
        if ($LASTEXITCODE -ne 0) { throw "git add failed" }
        & git commit -m $Message
        if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
        Write-Ok "Committed: $Message"
    } else {
        Write-Ok "Nothing to commit — working tree clean"
    }

    Write-Step "Pushing to GitHub (origin master)"
    & git push origin master
    if ($LASTEXITCODE -ne 0) { throw "git push failed" }
    Write-Ok "Push complete"

    # ── DIRECT SSH DEPLOY ─────────────────────────────────────────────────────
    if ($Direct) {
        Write-Step "Deploying directly via SSH to $SSH_HOST"
        Write-Warn "This mirrors what GitHub Actions does — builds image, migrates, restarts web"
        $code = Invoke-SSH @'
set -e
cd ~/sibanyetrack
git fetch --all
git reset --hard origin/master
docker build -t sibanyetrack-web:latest .
docker compose -f docker-compose.prod.yml up -d db
until docker compose -f docker-compose.prod.yml exec -T db pg_isready -U ${POSTGRES_USER:-postgres} > /dev/null 2>&1; do sleep 2; done
docker compose -f docker-compose.prod.yml run --rm --no-deps web python manage.py migrate --noinput
docker rm -f sibanyetrack-web-1 2>/dev/null || true
docker compose -f docker-compose.prod.yml up -d --no-deps web
echo "--- Running containers ---"
docker ps --filter name=sibanyetrack --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
'@
        if ($code -ne 0) { throw "Direct deploy failed (exit $code)" }
        Write-Ok "Deploy complete"
        Write-Host "`nhttps://sibanyetrack.mharetech.co.za" -ForegroundColor Green
    } else {
        Write-Host "`nGitHub Actions is deploying to sibanyetrack.mharetech.co.za" -ForegroundColor Yellow
        Write-Host "Track: https://github.com/MhareConsulting/sibanyetrack/actions" -ForegroundColor DarkYellow
    }

} catch {
    Write-Err $_
}

Write-Host ""
Read-Host "Press Enter to close"
