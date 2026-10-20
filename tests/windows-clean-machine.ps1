$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$folder = 'C:\CreativeKitAcceptance'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$archive = Join-Path $folder 'creative-kit.zip'
& curl.exe --fail --silent --show-error --location --retry 3 'https://codeload.github.com/wilsonhfwong/byteplus-creative-kit/zip/72481ecac66e42240f2a8f5fb95da1b9d1280243' --output $archive
if ($LASTEXITCODE -ne 0) { throw 'Public repository download failed.' }
Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $folder 'source') -Force
$root = (Get-ChildItem (Join-Path $folder 'source') -Directory | Select-Object -First 1).FullName
$plugin = Join-Path $root 'plugins\byteplus-creative-kit-windows'
$manifest = Get-Content -LiteralPath (Join-Path $plugin 'mcp.json') -Raw | ConvertFrom-Json
$command = $manifest.mcpServers.byteplus_creative.command.Replace('${PLUGIN_ROOT}', $plugin)
$data = Join-Path $folder ('Acceptance data with spaces ' + [Guid]::NewGuid().ToString('N'))
$report = [ordered]@{
  Windows = (Get-CimInstance Win32_OperatingSystem).Caption
  Version = [Environment]::OSVersion.Version.ToString()
  User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  Commit = '72481ecac66e42240f2a8f5fb95da1b9d1280243'
  PythonInitiallyAvailable = [bool](Get-Command python -ErrorAction SilentlyContinue)
  GitInitiallyAvailable = [bool](Get-Command git -ErrorAction SilentlyContinue)
  DockerInitiallyAvailable = [bool](Get-Command docker -ErrorAction SilentlyContinue)
  NativeBinarySha256 = (Get-FileHash -Algorithm SHA256 $command).Hash
}
$expected = ((Get-Content (Join-Path $plugin 'bin\SHA256SUMS') | Select-Object -First 1) -split '\s+')[0]
if ($report.NativeBinarySha256 -ine $expected) { throw 'Native launcher checksum mismatch.' }
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $command
$start.WorkingDirectory = $plugin
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
$start.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
$start.EnvironmentVariables['BYTEPLUS_CREATIVE_DATA_DIR'] = $data
$start.EnvironmentVariables['BYTEPLUS_CREATIVE_NO_BROWSER'] = '1'
$start.EnvironmentVariables['PATH'] = Join-Path $env:SystemRoot 'System32'
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
[void]$process.Start()
$process.StandardInput.AutoFlush = $true
$script:requestId = 0
function Request-Mcp($method, $parameters) {
  $script:requestId++
  $request = @{jsonrpc='2.0';id=$script:requestId;method=$method;params=$parameters}
  $process.StandardInput.WriteLine(($request | ConvertTo-Json -Depth 50 -Compress))
  $read = $process.StandardOutput.ReadLineAsync()
  if (-not $read.Wait(120000)) { throw ('MCP timed out: ' + $method) }
  if (-not $read.Result) { throw ('MCP closed: ' + $process.StandardError.ReadToEnd()) }
  $reply = $read.Result | ConvertFrom-Json
  if ($reply.error -or $reply.id -ne $script:requestId) { throw $read.Result }
  return $reply.result
}
function Invoke-McpTool($name, $arguments=@{}) {
  $reply = Request-Mcp 'tools/call' @{name=$name;arguments=$arguments}
  if ($reply.structuredContent) { return $reply.structuredContent }
  return (($reply.content | Where-Object type -eq 'text' | Select-Object -First 1).text | ConvertFrom-Json)
}
try {
  $timer = [Diagnostics.Stopwatch]::StartNew()
  $null = Request-Mcp 'initialize' @{protocolVersion='2025-11-25';capabilities=@{};clientInfo=@{name='clean-windows-acceptance';version='1'}}
  $tools = (Request-Mcp 'tools/list' @{}).tools
  $report.DiscoverySeconds = [Math]::Round($timer.Elapsed.TotalSeconds,3)
  $report.ToolCount = $tools.Count
  foreach ($name in @('creative_kit_setup','creative_kit_status','seedream_generate','seedance_image_to_video','seedance_library_import','seedance_library_delete_asset')) {
    if ($name -notin $tools.name) { throw ('Required tool missing: ' + $name) }
  }
  if ($timer.Elapsed.TotalSeconds -gt 15) { throw 'Discovery waited for runtime downloads.' }
  $initial = Invoke-McpTool 'creative_kit_status'
  if ($initial.runtime -ne 'not_prepared' -or $initial.generation_configured) { throw 'Initial state was not clean.' }
  $blocked = Invoke-McpTool 'seedream_generate' @{prompt='Do not submit a cloud request.'}
  if ($blocked.status -ne 'setup_required') { throw 'Unconfigured cloud call was not blocked.' }
  $setup = Invoke-McpTool 'creative_kit_setup'
  $url = [Uri]$setup.setup_url
  if ($url.Host -ne '127.0.0.1') { throw 'Setup server is not loopback-only.' }
  $page = Invoke-WebRequest -UseBasicParsing -Uri $url
  if ($page.Content -notmatch 'type="password"') { throw 'Credential form missing.' }
  $values = @{csrf=$url.AbsolutePath.Trim('/');api_key='dummy-api-windows-acceptance';access_key='dummy-iam-windows-acceptance';secret_key='dummy-secret-windows-acceptance';project='default';tos_bucket='dummy-private-bucket'}
  $origin = $url.GetLeftPart([UriPartial]::Authority)
  $saved = Invoke-WebRequest -UseBasicParsing -Uri $url -Method Post -Body $values -Headers @{Origin=$origin}
  foreach ($secret in @($values.api_key,$values.access_key,$values.secret_key)) {
    if ($saved.Content.Contains($secret)) { throw 'Credential was echoed into setup response.' }
  }
  $deadline = [DateTime]::UtcNow.AddMinutes(15)
  $previous = ''
  do {
    $status = Invoke-McpTool 'creative_kit_status'
    if ($status.runtime -ne $previous) { Write-Output ('Runtime: ' + $status.runtime); $previous = $status.runtime }
    if ($status.runtime -eq 'failed') { throw ($status | ConvertTo-Json -Depth 10) }
    $statusJson = $status | ConvertTo-Json -Depth 10
    foreach ($secret in @($values.api_key,$values.access_key,$values.secret_key)) {
      if ($statusJson.Contains($secret)) { throw 'Status exposed a credential.' }
    }
    if ($status.runtime -eq 'ready') { break }
    Start-Sleep -Seconds 2
  } while ([DateTime]::UtcNow -lt $deadline)
  if ($status.runtime -ne 'ready') { throw 'Managed runtime preparation timed out.' }
  $models = Invoke-McpTool 'seedream_list_models'
  if (($models | ConvertTo-Json -Depth 30) -notmatch 'seedream') { throw 'Python MCP worker failed.' }
  $invalid = Invoke-McpTool 'seedance_library_import' @{group_id='local-validation-only'}
  if (($invalid | ConvertTo-Json -Depth 30) -notmatch 'exactly one') { throw 'Asset-library local validation failed.' }
  if ((Invoke-McpTool 'seed_text' @{prompt='Do not call a cloud model.'}).status -ne 'setup_required') { throw 'Optional Seed model gate failed.' }
  if (Test-Path (Join-Path $plugin '.runtime')) { throw 'Runtime was written inside the plugin package.' }
  $report.Runtime = $status.runtime
  $report.TotalSeconds = [Math]::Round($timer.Elapsed.TotalSeconds,3)
  $report.Result = 'PASS'
  $report.PaidBytePlusCalls = 0
  $report | ConvertTo-Json -Depth 20 | Tee-Object -FilePath (Join-Path $folder 'plugin-acceptance.json')
} finally {
  if (-not $process.HasExited) {
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(10000)) { $process.Kill() }
  }
  if (Test-Path (Join-Path $data 'runtime-install.log')) { Get-Content (Join-Path $data 'runtime-install.log') | Select-Object -Last 8 }
}
