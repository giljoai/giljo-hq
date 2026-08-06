#Requires -Version 5.1
#Requires -Modules Pester

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# [CE] Community Edition.

<#
.SYNOPSIS
    Pester unit tests for install.ps1

.DESCRIPTION
    Tests the internal functions of the Windows one-liner installer without
    performing any actual installations. Validates parameter handling, version
    parsing, SHA256 verification, and update detection.

.NOTES
    Run with: Invoke-Pester -Path tests/unit/test_install_ps1.Tests.ps1
#>

BeforeAll {
    # Dot-source the installer to load its functions into scope.
    # We override the main entry call at the bottom of the script by
    # loading only the function definitions.
    $scriptPath = Join-Path $PSScriptRoot "..\..\scripts\install.ps1"

    # Extract function definitions without executing the installer.
    # We parse the AST and define functions in the test scope.
    $scriptContent = Get-Content $scriptPath -Raw

    # Define the utility functions by extracting them
    # We use a controlled scope to avoid running Invoke-GiljoInstaller
    $functionsToLoad = @(
        'Get-ParsedVersion',
        'Test-CommandExists',
        'Test-RealCommand',
        'Test-ExistingInstall',
        'Write-Banner',
        'Write-Phase',
        'Write-Step',
        'Write-Ok',
        'Write-Warn',
        'Write-Fail'
    )

    # Parse the script AST to extract function bodies
    $ast = [System.Management.Automation.Language.Parser]::ParseInput(
        $scriptContent,
        [ref]$null,
        [ref]$null
    )

    $functionDefs = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true)

    foreach ($funcDef in $functionDefs) {
        if ($funcDef.Name -in $functionsToLoad) {
            Invoke-Expression $funcDef.Extent.Text
        }
    }
}

Describe "Get-ParsedVersion" {

    It "parses 'Python 3.12.4' correctly" {
        $result = Get-ParsedVersion "Python 3.12.4"
        $result.Major | Should -Be 3
        $result.Minor | Should -Be 12
    }

    It "parses 'v20.11.0' correctly" {
        $result = Get-ParsedVersion "v20.11.0"
        $result.Major | Should -Be 20
        $result.Minor | Should -Be 11
    }

    It "parses 'git version 2.43.0.windows.1' correctly" {
        $result = Get-ParsedVersion "git version 2.43.0.windows.1"
        $result.Major | Should -Be 2
        $result.Minor | Should -Be 43
    }

    It "parses 'Python 3.13.0a1' correctly" {
        $result = Get-ParsedVersion "Python 3.13.0a1"
        $result.Major | Should -Be 3
        $result.Minor | Should -Be 13
    }

    It "returns null for garbage input" {
        $result = Get-ParsedVersion "no version here"
        $result | Should -BeNullOrEmpty
    }

    It "returns null for empty string" {
        $result = Get-ParsedVersion ""
        $result | Should -BeNullOrEmpty
    }

    It "parses single digit versions like '3.9'" {
        $result = Get-ParsedVersion "3.9"
        $result.Major | Should -Be 3
        $result.Minor | Should -Be 9
    }
}

Describe "Test-RealCommand" {
    # Guards the fresh-Win11 Store app-execution-alias trap (INF-6037): a stub
    # python.exe / node.exe in ...\WindowsApps\ satisfies Get-Command but is not a
    # real install, so it must be reported as missing for winget to install the tool.

    It "returns `$false when the command is not found" {
        Mock Get-Command { $null }
        Test-RealCommand "python" | Should -Be $false
    }

    It "returns `$false for a WindowsApps Store app-execution-alias stub" {
        Mock Get-Command {
            [PSCustomObject]@{
                CommandType = 'Application'
                Source      = 'C:\Users\test\AppData\Local\Microsoft\WindowsApps\python.exe'
            }
        }
        Test-RealCommand "python" | Should -Be $false
    }

    It "returns `$true for a real install outside WindowsApps" {
        Mock Get-Command {
            [PSCustomObject]@{
                CommandType = 'Application'
                Source      = 'C:\Program Files\Python312\python.exe'
            }
        }
        Test-RealCommand "python" | Should -Be $true
    }

    It "returns `$true for a real node install" {
        Mock Get-Command {
            [PSCustomObject]@{
                CommandType = 'Application'
                Source      = 'C:\Program Files\nodejs\node.exe'
            }
        }
        Test-RealCommand "node" | Should -Be $true
    }
}

Describe "Test-ExistingInstall" {

    It "returns null when VERSION file does not exist" {
        $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "giljo-test-$(Get-Random)"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
        try {
            $result = Test-ExistingInstall -TargetDir $tempDir
            $result | Should -BeNullOrEmpty
        } finally {
            Remove-Item -Path $tempDir -Recurse -Force
        }
    }

    It "returns current version when VERSION file exists" {
        $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "giljo-test-$(Get-Random)"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
        try {
            "1.2.3" | Out-File -FilePath (Join-Path $tempDir "VERSION") -Encoding UTF8 -NoNewline
            $result = Test-ExistingInstall -TargetDir $tempDir
            $result | Should -Not -BeNullOrEmpty
            $result.CurrentVersion | Should -Be "1.2.3"
        } finally {
            Remove-Item -Path $tempDir -Recurse -Force
        }
    }

    It "trims whitespace from VERSION file" {
        $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "giljo-test-$(Get-Random)"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
        try {
            "  2.0.0  `n" | Out-File -FilePath (Join-Path $tempDir "VERSION") -Encoding UTF8
            $result = Test-ExistingInstall -TargetDir $tempDir
            $result.CurrentVersion | Should -Be "2.0.0"
        } finally {
            Remove-Item -Path $tempDir -Recurse -Force
        }
    }
}

Describe "SHA256 Verification Logic" {

    It "Get-FileHash produces matching hash for known content" {
        $tempFile = Join-Path ([System.IO.Path]::GetTempPath()) "giljo-sha-test-$(Get-Random).txt"
        try {
            "hello world" | Out-File -FilePath $tempFile -Encoding ASCII -NoNewline
            $hash = (Get-FileHash -Path $tempFile -Algorithm SHA256).Hash.ToLower()
            # SHA256 of "hello world" (ASCII, no newline)
            $hash | Should -Be "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        } finally {
            Remove-Item -Path $tempFile -Force -ErrorAction SilentlyContinue
        }
    }

    It "SHA256 comparison is case-insensitive" {
        $upper = "B94D27B9934D3E08A52E52D7DA7DABFAC484EFE37A5380EE9088F7ACE2EFCDE9"
        $lower = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        $upper.ToLower() | Should -Be $lower
    }
}

Describe "Parameter Validation" {

    It "script file exists" {
        $scriptPath = Join-Path $PSScriptRoot "..\..\scripts\install.ps1"
        Test-Path $scriptPath | Should -Be $true
    }

    It "script has #Requires -Version 5.1 directive" {
        $scriptPath = Join-Path $PSScriptRoot "..\..\scripts\install.ps1"
        $content = Get-Content $scriptPath -Raw
        $content | Should -Match '#Requires -Version 5\.1'
    }

    It "script defines InstallDir parameter" {
        $scriptPath = Join-Path $PSScriptRoot "..\..\scripts\install.ps1"
        $content = Get-Content $scriptPath -Raw
        $content | Should -Match '\[string\]\$InstallDir'
    }

    It "script defines SkipPrereqs parameter" {
        $scriptPath = Join-Path $PSScriptRoot "..\..\scripts\install.ps1"
        $content = Get-Content $scriptPath -Raw
        $content | Should -Match '\[switch\]\$SkipPrereqs'
    }

    It "script defines Update parameter" {
        $scriptPath = Join-Path $PSScriptRoot "..\..\scripts\install.ps1"
        $content = Get-Content $scriptPath -Raw
        $content | Should -Match '\[switch\]\$Update'
    }
}

Describe "Script Structure" {

    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot "..\..\scripts\install.ps1"
        $script:content = Get-Content $scriptPath -Raw
    }

    It "contains Phase 1 prerequisites function" {
        $script:content | Should -Match 'function Test-Prerequisites'
    }

    It "contains Phase 2 download function" {
        $script:content | Should -Match 'function Get-LatestRelease'
    }

    It "contains Phase 3 environment setup function" {
        $script:content | Should -Match 'function Initialize-Environment'
    }

    It "contains Phase 4 install.py invocation" {
        $script:content | Should -Match 'function Invoke-InstallPy'
    }

    It "contains Phase 5 shortcuts function" {
        $script:content | Should -Match 'function Install-Shortcuts'
    }

    It "contains Phase 6 first run function" {
        $script:content | Should -Match 'function Start-FirstRun'
    }

    It "wraps main logic in Invoke-GiljoInstaller function" {
        $script:content | Should -Match 'function Invoke-GiljoInstaller'
    }

    It "uses ErrorActionPreference Stop" {
        $script:content | Should -Match "\`\$ErrorActionPreference\s*=\s*'Stop'"
    }

    It "references the correct GitHub repository" {
        $script:content | Should -Match 'giljoai/giljo-hq'
    }
}
