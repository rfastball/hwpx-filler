<#
.SYNOPSIS
  Inno Setup 6 컴파일러(ISCC.exe)의 위치를 찾는다. 없으면 $null.

.DESCRIPTION
  찾는 **사실**만 여기 있고, 없을 때 무엇을 할지의 **정책**은 호출자가 진다 — 설치본 러너는
  안내하고 종료하며, 패키징 게이트는 시끄럽게 던진다.

  후보 셋을 보는 이유는 실측이다: `winget install JRSoftware.InnoSetup` 은 관리자 권한 없이
  **사용자 범위**로 설치해 `%LOCALAPPDATA%\Programs\Inno Setup 6\` 에 놓고 PATH 에도 올리지
  않는다. 종전 탐색은 PATH 와 `Program Files (x86)` 둘뿐이라, 도구가 실제로 설치된 기기에서도
  "없다"고 말했다 — 있는데 없다고 하는 실패는 조용한 스킵만큼 나쁘다(사용자를 엉뚱한 조치로
  보낸다).
#>
[CmdletBinding()]
param()

$onPath = Get-Command iscc.exe -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($onPath) { return $onPath.Source }

foreach ($candidate in @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
}

return $null
