param(
    [string]$BaseUrl = "http://localhost:8000/api/v1",
    [string]$Email = "delivery-demo-lead@example.com",
    [string]$Password = "Demo123!",
    [string]$ExpectedWeakestTeam = "Customer Portal",
    [switch]$StrictLlm,
    [switch]$IncludeCompound,
    [switch]$ShowAnswer
)

$ErrorActionPreference = "Stop"
$script:Passed = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "FAIL: $Message"
    }
    $script:Passed += 1
    Write-Host "PASS: $Message" -ForegroundColor Green
}

function ConvertTo-Utf8Body {
    param([hashtable]$Value)
    $json = $Value | ConvertTo-Json -Depth 12 -Compress
    # Unary comma prevents PowerShell from unrolling byte[] into pipeline items.
    return ,([System.Text.Encoding]::UTF8.GetBytes($json))
}

function Invoke-DeliveryTurn {
    param(
        [string]$Message,
        [string]$ThreadId = ""
    )
    $body = @{
        message = $Message
        client_request_id = [guid]::NewGuid().ToString()
        persist_history = $false
    }
    if ($ThreadId) {
        $body.thread_id = $ThreadId
    }
    $started = Get-Date
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/workspaces/$($script:Organization.id)/agent-workspaces/$($script:Agent.id)/delivery/brief" `
        -Headers $script:Headers `
        -ContentType "application/json; charset=utf-8" `
        -Body (ConvertTo-Utf8Body $body) `
        -TimeoutSec 120
    return [pscustomobject]@{
        DurationSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
        Response = $response
    }
}

Write-Host "Product Delivery multi-agent acceptance smoke test" -ForegroundColor Cyan

$health = Invoke-RestMethod -Uri ($BaseUrl -replace "/api/v1$", "/health") -TimeoutSec 10
Assert-True ($health.status -eq "ok") "Backend health endpoint is ready"

$login = Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/auth/login" `
    -ContentType "application/json; charset=utf-8" `
    -Body (ConvertTo-Utf8Body @{ email = $Email; password = $Password })
$script:Headers = @{ Authorization = "Bearer $($login.access_token)" }
Assert-True ([bool]$login.access_token) "Demo Lead can authenticate"

$workspaces = Invoke-RestMethod -Uri "$BaseUrl/workspaces" -Headers $script:Headers
$script:Organization = $workspaces | Where-Object { $_.type -eq "organization" } | Select-Object -First 1
Assert-True ([bool]$script:Organization.id) "Organization workspace is available"

$agents = Invoke-RestMethod `
    -Uri "$BaseUrl/workspaces/$($script:Organization.id)/agent-workspaces/available" `
    -Headers $script:Headers
$script:Agent = $agents | Where-Object { $_.agent_profile -eq "product_delivery" } | Select-Object -First 1
Assert-True ([bool]$script:Agent.id) "Product Delivery Agent Workspace is assigned to Lead"

Write-Host "`nScenario A1 - evidence-backed meeting plan" -ForegroundColor Cyan
$meetingRun = Invoke-DeliveryTurn "Create an evidence-backed meeting plan for the lowest-completion team"
$meeting = $meetingRun.Response
$orchestration = $meeting.payload.orchestration
$expectedAgents = @("task_intelligence", "risk_dependency", "planning_forecast")
$requestedAgents = @($orchestration.specialists_requested)
$completedAgents = @($orchestration.specialists_completed)

Assert-True ($orchestration.intent -eq "meeting_plan") "Router selects meeting_plan intent"
Assert-True ($orchestration.execution_mode -eq "multi_specialist") "Request uses multi-specialist execution"
Assert-True (($requestedAgents -join ",") -eq ($expectedAgents -join ",")) "Workflow selects Task -> Risk -> Planning"
Assert-True (($completedAgents -join ",") -eq ($expectedAgents -join ",")) "All specialists complete in planned order"
Assert-True (@($orchestration.specialists_failed).Count -eq 0) "No specialist fails"
Assert-True ($orchestration.llm_calls -eq 4) "Three specialist LLM calls and one Supervisor call are recorded"
Assert-True ($orchestration.specialist_llm_attempts -eq 3) "Every specialist attempts its own LLM call"
$rejectedLlmResults = @($meeting.payload.specialist_results | Where-Object { -not $_.llm_used })
if ($StrictLlm) {
    Assert-True ($rejectedLlmResults.Count -eq 0) "Every specialist accepted an LLM result"
} elseif ($rejectedLlmResults.Count -gt 0) {
    Write-Warning "$($rejectedLlmResults.Count) specialist LLM result(s) used deterministic fallback: $($orchestration.specialist_fallbacks | ConvertTo-Json -Compress)"
}
Assert-True ($meeting.payload.meeting_plan.artifact_type -eq "meeting_plan.v1") "Planning produces meeting_plan.v1"
Assert-True ($meeting.payload.meeting_plan.target_group_name -eq $ExpectedWeakestTeam) "Weakest team is selected from current demo data"
Assert-True ($meeting.payload.meeting_plan.task_assessment.completion_percent -eq 15) "Target-team completion baseline is 15 percent"
Assert-True (@($meeting.payload.meeting_plan.dependency_brief).Count -ge 3) "Meeting plan contains concrete dependency chains"
Assert-True (@($meeting.payload.meeting_plan.action_items).Count -ge 1) "Meeting plan contains evidence-backed actions"
Assert-True ($meeting.payload.agent_response.Length -gt 200) "Supervisor returns a substantive business response"
Assert-True ($meetingRun.DurationSeconds -le 40) "Run completes within configured 40-second workflow deadline"

if ($ShowAnswer) {
    Write-Host "`n--- Agent response ---"
    Write-Host $meeting.payload.agent_response
}

Write-Host "`nScenario A2 - single-agent comparison" -ForegroundColor Cyan
$singleRun = Invoke-DeliveryTurn "Summarize tasks by group"
$single = $singleRun.Response.payload.orchestration
Assert-True ($single.intent -eq "task_progress_summary") "Task summary intent is selected"
Assert-True ($single.execution_mode -eq "single_specialist") "Task-only request does not fan out unnecessarily"
Assert-True (@($single.specialists_requested).Count -eq 1) "Exactly one specialist is requested"
Assert-True ($single.specialists_requested[0] -eq "task_intelligence") "Task Intelligence owns the single-domain request"
$taskResult = @($singleRun.Response.payload.specialist_results | Where-Object { $_.specialist -eq "task_intelligence" })[0]
$weakest = @($taskResult.artifact.teams | Where-Object { $_.group_name -eq $ExpectedWeakestTeam })[0]
Assert-True ($taskResult.artifact.artifact_type -eq "team_task_assessment.v1") "Task specialist returns a typed team assessment"
Assert-True ($taskResult.artifact.weakest_group_name -eq $ExpectedWeakestTeam) "Task artifact identifies the weakest team"
Assert-True ($weakest.completion_percent -eq 15) "Weakest-team artifact preserves the 15 percent baseline"
Assert-True (@($weakest.attention_tasks).Count -ge 3) "Weakest-team artifact includes concrete attention tasks"

Write-Host "`nScenario A3 - checkpoint progress handoff" -ForegroundColor Cyan
$checkpointRun = Invoke-DeliveryTurn "Checkpoint progress and pending Lead review"
$checkpointPayload = $checkpointRun.Response.payload
$checkpoint = $checkpointPayload.orchestration
$planningResult = @(
    $checkpointPayload.specialist_results |
        Where-Object { $_.specialist -eq "planning_forecast" }
)[0]
$checkpointFacts = @($planningResult.facts)
Assert-True ($checkpoint.intent -eq "checkpoint_progress") "Checkpoint request selects checkpoint_progress intent"
Assert-True ($checkpoint.execution_mode -eq "single_specialist") "Checkpoint request uses one specialist"
Assert-True ($checkpoint.specialists_requested[0] -eq "planning_forecast") "Planning owns checkpoint progress"
Assert-True (@($checkpoint.specialists_failed).Count -eq 0) "Planning specialist completes without failure"
Assert-True ($planningResult.metrics.checkpoint_count -ge 1) "Planning returns checkpoint rows"
Assert-True ($planningResult.metrics.checkpoint_overdue -ge 1) "Planning identifies an overdue checkpoint"
Assert-True (
    $planningResult.metrics.checkpoint_pending_quality_review -ge 1
) "Planning distinguishes pending Lead quality review"
Assert-True (
    @($checkpointFacts | Where-Object { $_.title -eq "Release 34 freeze readiness" }).Count -ge 1
) "Release 34 freeze readiness remains available through synthesis handoff"
Assert-True (
    $checkpointPayload.agent_response -notmatch "Snapshot.*(?:no|not).*checkpoint"
) "Supervisor does not make a false missing-checkpoint claim"

if ($IncludeCompound) {
    Write-Host "`nWaiting for provider cooldown before extended compound scenario..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 20
    Write-Host "Scenario A4 - compound cross-domain request" -ForegroundColor Cyan
    $compoundRun = Invoke-DeliveryTurn "Summarize tasks, classify dependencies, and create a meeting plan for low-performing teams"
    $compound = $compoundRun.Response.payload.orchestration
    if ($compound.execution_mode -ne "multi_specialist") {
        Write-Warning "Unexpected compound orchestration: $($compound | ConvertTo-Json -Depth 8 -Compress)"
    }
    Assert-True ($compound.execution_mode -eq "multi_specialist") "Compound request activates a multi-agent workflow"
    Assert-True (@($compound.specialists_requested).Count -eq 3) "Compound request calls three specialists"
    Assert-True (@($compound.specialists_completed).Count -eq 3) "Compound workflow completes all three specialists"
}

Write-Host "`nAcceptance smoke completed: $script:Passed assertions passed." -ForegroundColor Cyan
$durationLine = "Meeting-plan duration: $($meetingRun.DurationSeconds)s; single-agent duration: $($singleRun.DurationSeconds)s; checkpoint duration: $($checkpointRun.DurationSeconds)s"
if ($IncludeCompound) {
    $durationLine += "; compound duration: $($compoundRun.DurationSeconds)s"
}
Write-Host $durationLine
