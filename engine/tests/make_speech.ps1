# Synthesizes spoken test audio with the Windows built-in voice (offline).
# Usage: powershell -File make_speech.ps1 -Out speech.wav -TextFile script.txt
# Lines in the text file are spoken in order; an empty line inserts a 1.5 second pause.
param([Parameter(Mandatory)][string]$Out, [Parameter(Mandatory)][string]$TextFile)

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$prompt = New-Object System.Speech.Synthesis.PromptBuilder
foreach ($line in Get-Content -LiteralPath $TextFile -Encoding UTF8) {
    if ($line.Trim() -eq '') { $prompt.AppendBreak([TimeSpan]::FromMilliseconds(1500)) }
    else { $prompt.AppendText($line); $prompt.AppendBreak([TimeSpan]::FromMilliseconds(400)) }
}
$synth.SetOutputToWaveFile($Out)
$synth.Speak($prompt)
$synth.Dispose()
