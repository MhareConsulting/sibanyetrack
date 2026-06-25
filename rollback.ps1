param(
    [string]$Commit = "HEAD~1"
)

$SERVER     = "azureuser@20.164.200.242"
$REMOTE_DIR = "/home/azureuser/mytrack"
$COMPOSE    = "docker-compose.prod.yml"

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    OK: $Text" -ForegroundColor Green }

try {
    Write-Step "Recent commits on production server"
    & ssh $SERVER "cd $REMOTE_DIR && git log --oneline -8"
    if ($LASTEXITCODE -ne 0) { throw "Could not reach server - check SSH" }

    Write-Host "`nTarget: $Commit" -ForegroundColor Yellow
    $confirm = Read-Host "Roll back to this commit and rebuild? [y/N]"
    if ($confirm -notmatch '^[Yy]$') {
        Write-Host "Aborted." -ForegroundColor Gray
    } else {
        Write-Step "Rolling back on track.mharetech.co.za"

        $remoteScript = "set -e; cd $REMOTE_DIR; echo '--- current HEAD ---'; git log --oneline -1; echo '--- resetting to $Commit ---'; git reset --hard $Commit; echo '--- new HEAD ---'; git log --oneline -1; echo '--- docker build ---'; docker build -t mytrack-web:latest .; echo '--- docker compose up ---'; docker compose -f $COMPOSE up -d web; echo '--- done ---'"

        & ssh $SERVER $remoteScript
        if ($LASTEXITCODE -ne 0) { throw "Rollback failed - see output above" }

        Write-Ok "Rollback complete"
        Write-Host "`nSite: https://track.mharetech.co.za" -ForegroundColor Yellow
        Write-Host "Note: GitHub still has the reverted commits. Push a fix commit when ready." -ForegroundColor DarkYellow
    }

} catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
}

Write-Host ""
Read-Host "Press Enter to close"
