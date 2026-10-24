param(
    [Parameter(Mandatory = $true)][string]$BuildDir
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$revision = '52bc6d986aae93615673960256549f51f13c92b6'
# windows-latest ships Rust outside the default PATH for some shells.
$cargoBin = Join-Path $env:USERPROFILE '.cargo/bin'
if (Test-Path $cargoBin) { $env:PATH = "$cargoBin;$env:PATH" }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw 'cargo was not found; install a stable Rust toolchain before building the launcher'
}
function Invoke-Native([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
if (Test-Path $BuildDir) { throw "Build directory must be new: $BuildDir" }
Invoke-Native git @('clone', '--branch', 'v1.2.3', '--depth', '1', 'https://github.com/ok-oldking/pyappify.git', $BuildDir)
Push-Location $BuildDir
try {
    $actual = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $revision) { throw "Unexpected PyAppify revision: $actual" }
    Invoke-Native git @('apply', '--check', (Join-Path $PSScriptRoot 'pyappify-1.2.3.patch'))
    Invoke-Native git @('apply', (Join-Path $PSScriptRoot 'pyappify-1.2.3.patch'))
    Copy-Item (Join-Path $root 'pyappify.yml') 'src-tauri/assets/pyappify.yml'
    Copy-Item (Join-Path $root 'icons/*') 'src-tauri/icons' -Recurse -Force
    $configPath = Join-Path $BuildDir 'src-tauri/tauri.conf.json'
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $config.productName = 'ok-zzz'
    $config.mainBinaryName = 'ok-zzz'
    $config.identifier = 'ok-zzz'
    $config.version = '1.2.3'
    $config.app.windows[0].title = 'ok-zzz'
    [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 30))
    $cargoPath = Join-Path $BuildDir 'src-tauri/Cargo.toml'
    [IO.File]::WriteAllText($cargoPath, ([IO.File]::ReadAllText($cargoPath).Replace('name = "pyappify"', 'name = "ok-zzz"')))
    # The Windows libgit2 backend ignores git2's server timeout options and
    # hardcodes infinite WinHTTP resolve/send/receive waits. Patch a verified
    # private crate copy, never the shared Cargo registry.
    $archive = Join-Path $BuildDir 'libgit2-sys.crate'
    Invoke-WebRequest 'https://static.crates.io/crates/libgit2-sys/libgit2-sys-0.18.4%2B1.9.3.crate' -OutFile $archive
    $checksum = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($checksum -ne '9b26f66f35e1871b22efcf7191564123d2a446ca0538cde63c23adfefa9b15b7') {
        throw 'libgit2-sys source checksum mismatch'
    }
    New-Item -ItemType Directory 'vendor' | Out-Null
    Invoke-Native "$env:SystemRoot/System32/tar.exe" @('-xzf', $archive, '-C', 'vendor')
    $crateDir = Join-Path $BuildDir 'vendor/libgit2-sys-0.18.4+1.9.3'
    Push-Location $crateDir
    try {
        # Separate repository boundary: git apply inside an ignored vendor child
        # of the upstream checkout otherwise silently skips these paths.
        Invoke-Native git @('init', '--quiet')
        Invoke-Native git @('apply', '--check', (Join-Path $PSScriptRoot 'libgit2-winhttp.patch'))
        Invoke-Native git @('apply', (Join-Path $PSScriptRoot 'libgit2-winhttp.patch'))
        Invoke-Native git @('apply', '--reverse', '--check', (Join-Path $PSScriptRoot 'libgit2-winhttp.patch'))
    } finally { Pop-Location }
    [IO.File]::AppendAllText($cargoPath, "`n[patch.crates-io]`nlibgit2-sys = { path = '../vendor/libgit2-sys-0.18.4+1.9.3' }`n")
    $packagePath = Join-Path $BuildDir 'package.json'
    $package = Get-Content $packagePath -Raw | ConvertFrom-Json
    $package | Add-Member -Force NoteProperty pnpm @{ onlyBuiltDependencies = @('esbuild') }
    [IO.File]::WriteAllText($packagePath, ($package | ConvertTo-Json -Depth 30))
    Invoke-Native pnpm @('install', '--frozen-lockfile')
    # No installer is needed here: the existing packaging action reuses this
    # exact binary and performs online/offline bundling without recompilation.
    Invoke-Native pnpm @('tauri', 'build', '--no-bundle')
    Push-Location 'src-tauri'
    try {
        Invoke-Native cargo @('test', '--release', '--lib', 'stderr_tests', '--', '--nocapture')
    } finally { Pop-Location }
} finally { Pop-Location }
