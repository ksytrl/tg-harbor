param([string]$RepositoryName = 'tg-harbor')
$ErrorActionPreference = 'Stop'
$harborRepoRoot = $PSScriptRoot
$harborSafeDirectory = $harborRepoRoot -replace '\\','/'
$harborGhPath = Join-Path (Split-Path -Parent $harborRepoRoot) 'tg-harbor-publish-tools\cli\bin\gh.exe'
if (-not (Test-Path -LiteralPath $harborGhPath)) {
    $harborGhPath = (Get-Command gh -ErrorAction Stop).Source
}
$env:GH_CONFIG_DIR = Join-Path (Split-Path -Parent $harborRepoRoot) 'tg-harbor-publish-tools\gh-config'
$env:GH_PROMPT_DISABLED = '1'
$harborStateRoot = Join-Path $harborRepoRoot '.publish-runtime'
New-Item -ItemType Directory -Path $harborStateRoot -Force | Out-Null

function Invoke-HarborGh {
    param([string[]]$GhArguments)
    $harborResult = & $script:harborGhPath @GhArguments
    if ($LASTEXITCODE -ne 0) { throw ('GitHub 操作失败：' + ($GhArguments -join ' ')) }
    return $harborResult
}
function Invoke-HarborGit {
    param([string[]]$GitArguments)
    & git -c "safe.directory=$script:harborSafeDirectory" -C $script:harborRepoRoot @GitArguments
    if ($LASTEXITCODE -ne 0) { throw ('Git 操作失败：' + ($GitArguments -join ' ')) }
}
if ($RepositoryName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$') { throw '仓库名称格式不正确。' }
Invoke-HarborGh @('auth', 'status', '--active') | Out-Null
$harborUser = (Invoke-HarborGh @('api', 'user', '--jq', '{login: .login, id: .id}')) | ConvertFrom-Json
$harborStatePath = Join-Path $harborStateRoot 'publication.json'
$harborRepoFullName = "$($harborUser.login)/$RepositoryName"
if (Test-Path -LiteralPath $harborStatePath) {
    $harborPublication = Get-Content -LiteralPath $harborStatePath -Raw | ConvertFrom-Json
    if ($harborPublication.repository -ne $harborRepoFullName) { throw '当前登录账号或仓库名称与已创建的发布项目不同。' }
    $harborRemote = (Invoke-HarborGh @('api', "repos/$harborRepoFullName")) | ConvertFrom-Json
    if ($harborRemote.id -ne $harborPublication.repository_id) { throw '仓库身份已改变，已停止发布。' }
} else {
    $harborCreateBody = Join-Path $harborStateRoot 'create-repository.json'
    @{name=$RepositoryName;description='星港 TG Harbor · Windows Telegram 资源助手';private=$false;auto_init=$false;has_wiki=$false} | ConvertTo-Json | Set-Content -LiteralPath $harborCreateBody -Encoding utf8
    $harborRemote = (Invoke-HarborGh @('api', '--method', 'POST', 'user/repos', '--input', $harborCreateBody)) | ConvertFrom-Json
    $harborPublication = @{repository=$harborRemote.full_name;repository_id=$harborRemote.id;repository_url=$harborRemote.html_url;homepage_url=$null}
    $harborPublication | ConvertTo-Json | Set-Content -LiteralPath $harborStatePath -Encoding utf8
}
@{version='1.0.0';repository=$harborRemote.html_url} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $harborRepoRoot 'docs\site.json') -Encoding utf8
if (-not (Test-Path -LiteralPath (Join-Path $harborRepoRoot '.git'))) { Invoke-HarborGit @('init', '--initial-branch=main') }
Invoke-HarborGit @('config', 'user.name', $harborUser.login)
Invoke-HarborGit @('config', 'user.email', "$($harborUser.id)+$($harborUser.login)@users.noreply.github.com")
$harborExistingRemote = & git -c "safe.directory=$harborSafeDirectory" -C $harborRepoRoot remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) { Invoke-HarborGit @('remote', 'add', 'origin', $harborRemote.clone_url) }
elseif ($harborExistingRemote -ne $harborRemote.clone_url) { throw '已有远程地址与本次创建的仓库不同。' }
$harborCredentialHelper = '!"' + ($harborGhPath -replace '\\','/') + '" auth git-credential'
Invoke-HarborGit @('config', 'credential.https://github.com.helper', $harborCredentialHelper)
Invoke-HarborGit @('add', '--all')
$harborChanged = & git -c "safe.directory=$harborSafeDirectory" -C $harborRepoRoot diff --cached --name-only
if ($harborChanged) { Invoke-HarborGit @('commit', '-m', 'Publish TG Harbor 1.0 and project website') }
Invoke-HarborGit @('push', '--set-upstream', 'origin', 'main')

$harborPages = & $harborGhPath api "repos/$harborRepoFullName/pages" 2>$null
if ($LASTEXITCODE -ne 0) {
    $harborPagesBody = Join-Path $harborStateRoot 'create-pages.json'
    @{build_type='legacy';source=@{branch='main';path='/docs'}} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $harborPagesBody -Encoding utf8
    $harborPages = Invoke-HarborGh @('api', '--method', 'POST', "repos/$harborRepoFullName/pages", '--input', $harborPagesBody)
}
$harborPagesResult = $harborPages | ConvertFrom-Json
if (-not $harborPagesResult.html_url) { throw 'GitHub 未返回主页地址，请查看 Pages 状态。' }
$harborHomepage = $harborPagesResult.html_url
$harborMetadataBody = Join-Path $harborStateRoot 'repository-metadata.json'
@{homepage=$harborHomepage} | ConvertTo-Json | Set-Content -LiteralPath $harborMetadataBody -Encoding utf8
Invoke-HarborGh @('api', '--method', 'PATCH', "repos/$harborRepoFullName", '--input', $harborMetadataBody) | Out-Null
$harborPublication.homepage_url = $harborHomepage
$harborPublication | ConvertTo-Json | Set-Content -LiteralPath $harborStatePath -Encoding utf8
Write-Output ('公开源码仓库：' + $harborRemote.html_url)
Write-Output ('GitHub 返回的主页地址：' + $harborHomepage)
Write-Output 'Pages 正在构建。需检查构建成功且网页可访问后，再将主页地址填写到 Telegram 申请表。'
