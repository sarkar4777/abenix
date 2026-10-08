# Builds question.wav for uat_meetings_ui.spec.ts with the offline Windows voice.
# Usage: powershell -ExecutionPolicy Bypass -File e2e/fixtures/meetings/make-question-wav.ps1
Add-Type -AssemblyName System.Speech
$out = Join-Path $PSScriptRoot 'question.wav'
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = -1
$s.SetOutputToWaveFile($out, $fmt)
$p = New-Object System.Speech.Synthesis.PromptBuilder
$p.AppendBreak([TimeSpan]::FromSeconds(1))
$p.AppendText('Hey assistant, what is the status of the project roadmap?')
$p.AppendBreak([TimeSpan]::FromSeconds(25))
$p.AppendText('Hey assistant, who do you think will win the football match tonight?')
$p.AppendBreak([TimeSpan]::FromSeconds(2))
$s.Speak($p)
$s.Dispose()
Write-Output "wrote $out"
