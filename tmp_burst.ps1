param([int]$N = 200, [string]$Url = "http://localhost:8000/api/executions?limit=20")

$body = @{ email = "admin@abenix.dev"; password = "Admin123456" } | ConvertTo-Json
$r = Invoke-WebRequest -Uri "http://localhost:8000/api/auth/login" -Method POST -ContentType "application/json" -Body $body -TimeoutSec 5 -UseBasicParsing
$tok = ($r.Content | ConvertFrom-Json).data.access_token

Add-Type -AssemblyName System.Net.Http

$handler = New-Object System.Net.Http.HttpClientHandler
$handler.MaxConnectionsPerServer = 500
$client = New-Object System.Net.Http.HttpClient($handler)
$client.Timeout = [TimeSpan]::FromSeconds(90)
$client.DefaultRequestHeaders.Add("Authorization", "Bearer $tok")

$tasks = New-Object 'System.Collections.Generic.List[object]'
$starts = New-Object 'System.Collections.Generic.List[double]'
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# Fire all N requests as fast as possible
for ($i = 0; $i -lt $N; $i++) {
    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $Url)
    $starts.Add($sw.Elapsed.TotalMilliseconds)
    $tasks.Add($client.SendAsync($req))
}
$fireDoneMs = $sw.Elapsed.TotalMilliseconds

# Wait for completions
$results = @()
for ($i = 0; $i -lt $N; $i++) {
    $t = $tasks[$i]
    $startMs = $starts[$i]
    try {
        $resp = $t.GetAwaiter().GetResult()
        $endMs = $sw.Elapsed.TotalMilliseconds
        $latency = $endMs - $startMs
        $results += [pscustomobject]@{ ms = $latency; code = [int]$resp.StatusCode; err = $null }
        $resp.Dispose()
    } catch {
        $endMs = $sw.Elapsed.TotalMilliseconds
        $latency = $endMs - $startMs
        $results += [pscustomobject]@{ ms = $latency; code = 0; err = $_.Exception.InnerException.Message }
    }
}
$sw.Stop()

$latencies = $results | ForEach-Object { $_.ms } | Sort-Object
$count = $latencies.Count
$p50 = $latencies[[int]($count * 0.50)]
$p95 = $latencies[[int]($count * 0.95)]
$p99 = $latencies[[int]($count * 0.99)]
$avg = ($latencies | Measure-Object -Average).Average
$max = ($latencies | Measure-Object -Maximum).Maximum
$min = ($latencies | Measure-Object -Minimum).Minimum

Write-Output "==== BURST RESULTS ===="
Write-Output "N=$N URL=$Url"
Write-Output "FIRE_MS=$([math]::Round($fireDoneMs,1)) WALL_SEC=$([math]::Round($sw.Elapsed.TotalSeconds,2))"
Write-Output "RPS=$([math]::Round($count / $sw.Elapsed.TotalSeconds, 1))"
Write-Output "min=$([math]::Round($min,1)) avg=$([math]::Round($avg,1)) p50=$([math]::Round($p50,1)) p95=$([math]::Round($p95,1)) p99=$([math]::Round($p99,1)) max=$([math]::Round($max,1))"
Write-Output "STATUS:"
$results | Group-Object code | Sort-Object Name | ForEach-Object { Write-Output ("  HTTP {0} -> {1}" -f $_.Name, $_.Count) }
$errs = $results | Where-Object { $_.err } | Group-Object err
if ($errs) {
    Write-Output "ERRORS:"
    $errs | ForEach-Object { Write-Output ("  {0} -> {1}" -f $_.Name, $_.Count) }
}
$client.Dispose()
