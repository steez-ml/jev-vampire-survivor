param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Debug',

    [string]$GameDir = ''
)

$solutionPath = Join-Path $PSScriptRoot 'VampireSurvivorsJev.sln'

$buildArguments = @(
    'build',
    $solutionPath,
    '-c',
    $Configuration
)

if ($GameDir -ne '') {
    $buildArguments += "-p:GameDir=$GameDir"
}

& dotnet @buildArguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
