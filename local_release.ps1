# Builds the release installers on this machine, running the same steps as .github/workflows/release-en.yml.
# Use it when Actions is unavailable, or when the repo's "actions must be owned by <owner>" policy blocks the
# third-party actions the workflow needs. It tags and pushes for you. Creating the GitHub release and uploading
# the files stay manual. It differs from the workflow in one deliberate way, noted at the tag check below.
#
#   .\local_release.ps1 -Version 2026.8.26
#
# Needs git, Node, pnpm, a Rust MSVC toolchain with the VS C++ build tools, and Python 3.12 on PATH.
# Run it from an elevated PowerShell, since building the offline package runs the launcher as administrator.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    # Skip the test run. The workflow always runs them, so only use this to re-build a version already tested.
    [switch]$SkipTests,

    # Keep the scratch tree so a failed build can be inspected or resumed.
    [switch]$KeepScratch
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'UTF-8'

$RepoRoot = $PSScriptRoot
$ExpectedGitUrl = 'https://github.com/steve1316/ok-gf2-english.git'
$PyappifyActionRepo = 'https://github.com/ok-oldking/pyappify-action.git'

# PowerShell hoists the trap below to the top of the scope, so this has to be set before anything can fail.
$TagPushed = $false

function Write-Step($message) {
    Write-Host ''
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Invoke-Checked($file, $arguments, $workingDirectory) {
    # Native tools signal failure through the exit code, which PowerShell will not turn into a terminating error.
    Write-Host "    $file $($arguments -join ' ')" -ForegroundColor DarkGray
    $previous = $PWD
    if ($workingDirectory) { Set-Location $workingDirectory }
    try {
        & $file @arguments
        if ($LASTEXITCODE -ne 0) { throw "$file exited with $LASTEXITCODE" }
    } finally {
        Set-Location $previous
    }
}

# pyappify compares version parts as numbers rather than as text, so pad them into a key that sorts the same way.
function Get-VersionKey($tag) {
    return (($tag.TrimStart('v') -split '\.') | ForEach-Object { '{0:D6}' -f [int]$_ }) -join '.'
}

# Returns the release tags on origin as a name to commit map. An annotated tag lists its own object SHA and then
# a peeled 'refs/tags/<tag>^{}' line holding the commit, so the peeled line overwrites the tag object.
function Get-RemoteReleaseTags {
    $lines = & git -C $RepoRoot ls-remote --tags origin 'refs/tags/v*'
    if ($LASTEXITCODE -ne 0) { throw 'git ls-remote failed, cannot read the tags on origin.' }
    $tags = @{}
    foreach ($line in @($lines)) {
        $sha, $ref = $line -split '\s+', 2
        $name = ($ref -replace '^refs/tags/', '') -replace '\^\{\}$', ''
        if ($name -match '^v\d+\.\d+\.\d+$') { $tags[$name] = $sha }
    }
    return $tags
}

# //////////////////////////////////////////////////////////////////////////////////////////////////
# //////////////////////////////////////////////////////////////////////////////////////////////////
# Preflight

Write-Step 'Checking the version and settling the tag'
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must look like 2026.8.26, got '$Version'."
}
$Tag = "v$Version"
Write-Host "    Releasing as $Tag"

# The offline package is produced by running the freshly built launcher, whose manifest is requireAdministrator
# because pyappify.yml sets uac: true. From an ordinary shell that spawn fails with EACCES, and it fails late,
# once the tag has already gone out. CI never sees this because Actions runners are already elevated.
Write-Step 'Checking the shell is elevated'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this from an elevated PowerShell. Building the offline package runs the launcher, which requires administrator.'
}

Write-Step 'Checking the toolchain'
foreach ($tool in 'git', 'node', 'pnpm', 'cargo', 'python') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on PATH." }
}
$pythonVersion = (& python --version 2>&1) -replace '^Python\s+', ''
if ($pythonVersion -notmatch '^3\.12\.') { throw "Python 3.12 required, found $pythonVersion." }
Write-Host "    python $pythonVersion, node $(& node --version), $(& cargo --version)"

# The committed manifest is what pyappify re-reads on every launch, so a wrong git_url here ships an
# installer that replaces itself with someone else's code. Same guard the workflow runs.
Write-Step 'Checking pyappify.yml points at this fork'
$urls = Select-String -Path (Join-Path $RepoRoot 'pyappify.yml') -Pattern 'git_url:\s*"?([^"\s]+)"?' -AllMatches |
    ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value }
if (-not $urls) { throw 'pyappify.yml declares no git_url.' }
foreach ($url in $urls) {
    if ($url -ne $ExpectedGitUrl) { throw "pyappify.yml points at '$url', expected '$ExpectedGitUrl'." }
}
Write-Host "    pyappify.yml points at $ExpectedGitUrl"

# One git call for both, since the subject becomes the tag message further down.
$commitLines = @(& git -C $RepoRoot log -1 '--pretty=%H%n%s' HEAD)
if ($LASTEXITCODE -ne 0) { throw 'git log failed, cannot read the commit to build.' }
$commit = $commitLines[0].Trim()
$subject = $commitLines[1].Trim()
$dirty = & git -C $RepoRoot status --porcelain
if ($dirty) {
    Write-Warning 'The working tree has uncommitted changes. Only committed work is built, matching CI.'
    Write-Host ($dirty | Out-String)
}
Write-Host "    Building commit $commit"

# The build seeds the installer from whichever release tag is newest on origin, not from the tag the files are
# named after, so releasing anything but the newest version ships the wrong code under the right filename. That
# is how a v2026.8.30 installer came to hold v2026.8.26. Check it here, before the slow work, and push below.
Write-Step 'Checking the tag will be the newest on origin'
$RemoteTags = Get-RemoteReleaseTags
$tagKey = Get-VersionKey $Tag
$newer = @($RemoteTags.Keys | Where-Object { (Get-VersionKey $_) -gt $tagKey } | Sort-Object)
if ($newer) {
    throw "origin already has $($newer -join ', '), which outrank $Tag. The build would seed the installer from the newest of those."
}
if ($RemoteTags.ContainsKey($Tag)) {
    # The workflow refuses an existing tag outright. Here a re-build of the same commit is allowed instead, so
    # that a run which failed after the push can be resumed with -SkipTests.
    if ($RemoteTags[$Tag] -ne $commit) {
        throw "$Tag is already on origin at $($RemoteTags[$Tag]), not $commit. Release a new version instead."
    }
    Write-Host "    $Tag is already on origin at $commit, reusing it"
} else {
    Write-Host "    $Tag will be the newest tag on origin"
}

# //////////////////////////////////////////////////////////////////////////////////////////////////
# //////////////////////////////////////////////////////////////////////////////////////////////////
# Scratch tree

# inline_ok_requirements rewrites src/config.py, copies packages into the tree and edits requirements.txt.
# CI gets a throwaway checkout each run, so build from a clone and leave the real working tree alone.
$Scratch = Join-Path ([System.IO.Path]::GetTempPath()) "ok-gf2-release-$Tag"
$BuildTree = Join-Path $Scratch 'repo'
$ActionDir = Join-Path $Scratch 'pyappify-action'
$Venv = Join-Path $Scratch 'venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'

Write-Step "Preparing the scratch tree at $Scratch"
if (Test-Path $Scratch) { Remove-Item -Recurse -Force $Scratch }
New-Item -ItemType Directory -Path $Scratch | Out-Null
Invoke-Checked 'git' @('clone', '--quiet', $RepoRoot, $BuildTree)
Invoke-Checked 'git' @('checkout', '--quiet', '--detach', $commit) $BuildTree

Write-Step 'Installing dependencies into a fresh venv'
Invoke-Checked 'python' @('-m', 'venv', $Venv)
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip')
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--quiet', '-r', (Join-Path $BuildTree 'requirements.txt'))
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--quiet', 'cython', 'setuptools', 'polib')

if (-not $SkipTests) {
    Write-Step 'Running tests'
    # Each module runs in its own process: the ok framework installs a process-wide singleton that a
    # second init in the same process would trip over.
    Get-ChildItem -LiteralPath (Join-Path $BuildTree 'tests') -Filter 'Test*.py' | Sort-Object Name | ForEach-Object {
        $module = "tests.$([System.IO.Path]::GetFileNameWithoutExtension($_.Name))"
        Invoke-Checked $VenvPython @('-u', '-m', 'unittest', $module, '-v') $BuildTree
    }
} else {
    Write-Warning 'Skipping tests at your request. The workflow would have run them.'
}

# The tag goes up only once the tests have passed, but it has to be on origin before the build, since that is
# where the clone pyappify seeds the installer from will look for it.
if (-not $RemoteTags.ContainsKey($Tag)) {
    Write-Step 'Putting the tag on origin before the build'
    Invoke-Checked 'git' @('-C', $RepoRoot, 'tag', '-a', $Tag, '-m', $subject, $commit)
    Invoke-Checked 'git' @('-C', $RepoRoot, 'push', 'origin', $Tag)
    $TagPushed = $true
}

trap {
    # Installed apps follow git tags, not releases, so a tag left behind by a failed run is picked up by
    # everyone on AUTO_UPDATE even though there is nothing to download.
    if ($TagPushed) {
        Write-Host ''
        Write-Warning "The run failed after $Tag was pushed. Take it back unless you are rebuilding now:"
        Write-Host "  git push --delete origin $Tag"
        Write-Host "  git tag -d $Tag"
    }
    break
}

# Writes the tag into src/config.py so the app reports its own version, copies ok-script into the tree,
# and drops it from requirements.txt. The build needs all three.
Write-Step 'Running inline_ok_requirements'
Invoke-Checked $VenvPython @('-m', 'ok.update.inline_ok_requirements', '--tag', $Tag) $BuildTree

# //////////////////////////////////////////////////////////////////////////////////////////////////
# //////////////////////////////////////////////////////////////////////////////////////////////////
# Build

# pyappify-action is a Node action whose dist/index.js is a self-contained ncc bundle, so it runs outside a
# runner as long as the inputs it reads are in the environment. That keeps this identical to CI rather than
# being a second implementation of the same packaging steps that could drift.
Write-Step 'Fetching pyappify-action'
Invoke-Checked 'git' @('clone', '--quiet', '--depth', '1', $PyappifyActionRepo, $ActionDir)

Write-Step 'Building the installers (this compiles Rust and Tauri, expect a long first run)'
$env:INPUT_BUILD_EXE_ONLY = 'false'
$env:RUNNER_TEMP = Join-Path $Scratch 'runner-temp'
$env:GITHUB_OUTPUT = Join-Path $Scratch 'action-output.txt'
New-Item -ItemType Directory -Path $env:RUNNER_TEMP -Force | Out-Null
New-Item -ItemType File -Path $env:GITHUB_OUTPUT -Force | Out-Null
# The venv's python must win, since the action's setup step shells out to whatever python it finds.
$env:PATH = "$(Join-Path $Venv 'Scripts');$env:PATH"
Invoke-Checked 'node' @((Join-Path $ActionDir 'dist\index.js')) $BuildTree

$DistDir = Join-Path $BuildTree 'pyappify_dist'
if (-not (Test-Path $DistDir)) { throw "The build produced no $DistDir." }

Write-Step 'Adding the version to the build filenames'
Get-ChildItem -Path $DistDir -File | ForEach-Object {
    Rename-Item -LiteralPath $_.FullName -NewName "$($_.BaseName)-$Tag$($_.Extension)"
}

# //////////////////////////////////////////////////////////////////////////////////////////////////
# //////////////////////////////////////////////////////////////////////////////////////////////////
# Collect

$OutDir = Join-Path $RepoRoot "pyappify_dist"
Write-Step "Collecting the artifacts into $OutDir"
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Path $OutDir | Out-Null
Copy-Item -Path (Join-Path $DistDir '*') -Destination $OutDir -Recurse

Get-ChildItem -Path $OutDir -File | ForEach-Object {
    $size = '{0:N1} MB' -f ($_.Length / 1MB)
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLower()
    Write-Host ('    {0,-52} {1,10}  {2}' -f $_.Name, $size, $hash.Substring(0, 16))
}

if (-not $KeepScratch) {
    Remove-Item -Recurse -Force $Scratch -ErrorAction SilentlyContinue
} else {
    Write-Host "    Scratch tree kept at $Scratch"
}

Write-Host ''
Write-Host "Built $Tag from $commit." -ForegroundColor Green
Write-Host 'Publishing the release is still manual:' -ForegroundColor Yellow
Write-Host "  Create the release at https://github.com/steve1316/ok-gf2-english/releases/new?tag=$Tag"
Write-Host "  Upload every file in $OutDir"
