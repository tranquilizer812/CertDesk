# install-skills.ps1
# Скрипт для установки всех скиллов skills.sh, необходимых для проекта CertDesk
# Запуск: .\install-skills.ps1 (из папки C:\CertDesk)

$ErrorActionPreference = "Stop"

Write-Host "=== Установка скиллов для CertDesk ===" -ForegroundColor Cyan

$skills = @(
    @{ package = "mattpocock/skills"; skill = "code-review" },
    @{ package = "mattpocock/skills"; skill = "implement" },
    @{ package = "mattpocock/skills"; skill = "to-spec" },
    @{ package = "mattpocock/skills"; skill = "diagnosing-bugs" },
    @{ package = "vercel-labs/agent-skills"; skill = "web-design-guidelines" }
)

foreach ($s in $skills) {
    Write-Host "`nУстановка $($s.skill) из $($s.package)..." -ForegroundColor Yellow
    $cmd = "npx skills add $($s.package) --skill $($s.skill) --full-depth -y"
    Write-Host "Команда: $cmd" -ForegroundColor Gray
    & npx skills add $s.package --skill $s.skill --full-depth -y
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Ошибка при установке $($s.skill)" -ForegroundColor Red
    } else {
        Write-Host "$($s.skill) установлен успешно" -ForegroundColor Green
    }
}

Write-Host "`n=== Установка завершена ===" -ForegroundColor Cyan
Write-Host "Список установленных скиллов: npx skills list" -ForegroundColor Gray