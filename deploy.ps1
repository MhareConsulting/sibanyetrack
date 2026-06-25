param(
    [string]$Message = ""
)

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    OK: $Text" -ForegroundColor Green }

try {
    Write-Step "Checking for changes"

    $status = & git status --porcelain 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git status failed: $status" }

    if (-not $status) {
        Write-Ok "Nothing to commit - working tree clean"
    } else {
        if ($Message -eq "") {
            $Message = Read-Host "Commit message"
            if ($Message -eq "") { throw "Commit message cannot be empty" }
        }

        & git add -A
        if ($LASTEXITCODE -ne 0) { throw "git add failed" }

        & git commit -m $Message
        if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

        Write-Ok "Committed: $Message"
    }

    Write-Step "Pushing to GitHub (origin master)"
    & git push origin master
    if ($LASTEXITCODE -ne 0) { throw "git push failed" }
    Write-Ok "Push complete"

    Write-Host "`nGitHub Actions is now deploying to sibanyetrack.mharetech.co.za" -ForegroundColor Yellow
    Write-Host "Track progress: https://github.com/MhareConsulting/sibanyetrack/actions" -ForegroundColor DarkYellow

} catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
}

Write-Host ""
Read-Host "Press Enter to close"
