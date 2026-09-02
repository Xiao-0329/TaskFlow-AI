# TaskFlow AI → GitHub 一键推送脚本
# 网络恢复后运行本脚本即可推送（也可等后台自动重试成功）
# 用法：powershell -ExecutionPolicy Bypass -File push.ps1

$git = "$env:TEMP\PortableGit\cmd\git.exe"
# 便携 git 若不存在，回退系统 git
if (-not (Test-Path $git)) { $git = "git" }

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$remote = "https://x-access-token:$env:GH_TOKEN@github.com/Xiao-0329/TaskFlow-AI.git"

Write-Host "推送到 GitHub..." -ForegroundColor Cyan
$ok = $false
foreach ($i in 1..10) {
    & $git push $remote master:master 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Write-Host "  第${i}次失败，10秒后重试..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}
if ($ok) {
    Write-Host "推送成功！ https://github.com/Xiao-0329/TaskFlow-AI" -ForegroundColor Green
} else {
    Write-Host "推送失败：GitHub 目前不可达（VPN 节点断开/DNS 污染）。" -ForegroundColor Red
    Write-Host "建议：打开 iKuuu VPN 客户端，切换或重连节点后重跑本脚本。" -ForegroundColor Yellow
}
