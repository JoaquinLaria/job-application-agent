# Internal helper for docx_to_pdf.py. Converts exactly one LOCAL docx (never
# a OneDrive path) to a LOCAL pdf. No timeout logic here on purpose: the
# caller enforces a hard, OS-level kill, because a PowerShell-side timeout
# (Wait-Job, etc.) proved unreliable when Word itself is the thing stuck.
param(
    [Parameter(Mandatory = $true)][string]$InDocx,
    [Parameter(Mandatory = $true)][string]$OutPdf
)
$ErrorActionPreference = "Stop"
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($InDocx, $false, $false, $false)
    $doc.SaveAs($OutPdf, 17)
    $doc.Close($false)
}
finally {
    $word.Quit($false)
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
}
