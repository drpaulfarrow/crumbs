# Start the demo: lanes, system DNS server, control panel, and the A/B browser windows.
#   scripts\windows\start-demo.ps1                 # A/B windows open the real sites in demo_config.json
#   scripts\windows\start-demo.ps1 -Page test      # A/B windows open the Prebid test page
#   scripts\windows\start-demo.ps1 -Local          # use the local EasyPrivacy list instead of the Crumbs resolver
#   scripts\windows\start-demo.ps1 -NoLaunch       # just the panel; open windows from its buttons
param(
    [ValidateSet("site", "test")] [string] $Page = "site",
    [switch] $Local,
    [switch] $NoLaunch,
    [switch] $BlockAds
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "Run scripts\windows\setup.ps1 first." }

$cliArgs = @("-m", "crumbs_demo", "run", "--page", $Page)
if (-not $NoLaunch) { $cliArgs += "--launch" }
if ($Local) { $cliArgs += @("--crumbs-resolver", "local") }
if ($BlockAds) { $cliArgs += "--block-ads" }
& $venvPy @cliArgs
