param(
    [Parameter(Mandatory = $true)][string]$Cases,
    [Parameter(Mandatory = $true)][string]$Report,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Output) { throw 'Output already exists' }
$caseDocument = Get-Content -Raw -LiteralPath $Cases | ConvertFrom-Json
$score = Get-Content -Raw -LiteralPath $Report | ConvertFrom-Json
$caseHash = (Get-FileHash -LiteralPath $Cases).Hash.ToLowerInvariant()
if ($caseHash -ne $score.hashes.cases_json_sha256) {
    throw 'Score does not bind to these exact frozen cases'
}
$rows = @(
    foreach ($case in $caseDocument.cases | Where-Object { $_.review_only }) {
        $errors = [System.Collections.Generic.List[string]]::new()
        $result = @($score.cases | Where-Object { $_.id -ceq $case.id })
        if ($result.Count -ne 1 -or $result[0].execution_state -ne 'executed') {
            throw "Case did not execute exactly once: $($case.id)"
        }
        $result = $result[0]
        $nodes = @($result.actual_graph.condition_nodes)
        $localLine = @($case.text -split "`n" | Where-Object {
            $_.StartsWith($case.conflicting_group_quote, [StringComparison]::Ordinal)
        })
        if ($localLine.Count -ne 1) { throw "Ambiguous local line: $($case.id)" }
        $local = @($nodes | Where-Object { $_.text -ceq $localLine[0] })
        if ($local.Count -ne 1 -or $local[0].op -ne 'ATOM' -or
            $local[0].status -notin @('candidate', 'unresolved')) {
            $errors.Add('Conflicting local instruction is not one retained review ATOM')
        }
        foreach ($node in $nodes) {
            if ($node.op -in @('AND', 'OR') -and
                $node.text.StartsWith($case.conflicting_group_quote,
                    [StringComparison]::Ordinal) -and
                ($node.status -eq 'confirmed' -or
                    $node.operator_relation.status -eq 'confirmed' -or
                    $node.scope_relation.status -eq 'confirmed')) {
                $errors.Add('Conflicting local instruction still confirms a logical group')
            }
        }
        $header = ($case.text -split "`n")[0]
        $outer = @($nodes | Where-Object { $_.op -eq 'AND' -and $_.text -ceq $header })
        if ($outer.Count -ne 1 -or
            $outer[0].status -notin @('candidate', 'unresolved') -or
            $outer[0].scope_relation.status -notin @('candidate', 'unresolved') -or
            @($outer[0].children).Count -ne 2) {
            $errors.Add('Outer complete relation/scope is not retained as two review branches')
        }
        $unaffected = @($nodes | Where-Object {
            $_.op -eq 'OR' -and $_.text -match '^第[一二]组' -and
            -not $_.text.StartsWith($case.conflicting_group_quote,
                [StringComparison]::Ordinal)
        })
        if ($unaffected.Count -ne 1 -or $unaffected[0].status -ne 'confirmed' -or
            $unaffected[0].operator_relation.status -ne 'confirmed' -or
            $unaffected[0].scope_relation.status -ne 'confirmed' -or
            @($unaffected[0].children).Count -ne 2) {
            $errors.Add('Unconflicted local OR was incorrectly blocked or changed')
        }
        if ($result.source_identity.status -ne 'registry_verified' -or
            $result.source_validation.invalid_references -ne 0 -or
            $result.source_validation.checked_references -le 0) {
            $errors.Add('Source identity or raw-coordinate validation failed')
        }
        [ordered]@{
            id = $case.id
            status = $(if ($errors.Count -eq 0) { 'passed' } else { 'failed' })
            errors = @($errors)
            local_nodes = @($local | Select-Object node_id, op, status, text)
            outer_nodes = @($outer | ForEach-Object {
                [ordered]@{
                    node_id = $_.node_id
                    status = $_.status
                    operator_status = $_.operator_relation.status
                    scope_status = $_.scope_relation.status
                    direct_children = @($_.children)
                }
            })
            unaffected_or_nodes = @($unaffected | Select-Object node_id, op, status, text)
        }
    }
)
$record = [ordered]@{
    schema = 'inherited-or-local-review-inspection-v1'
    generated_at = (Get-Date -Format o)
    input_report_sha256 = (Get-FileHash -LiteralPath $Report).Hash.ToLowerInvariant()
    cases_sha256 = $caseHash
    source_tree_sha256 = $score.hashes.source_tree_sha256
    scope = 'Separate exact local-line/outer-state inspection; does not modify frozen scorer or assert business qualification.'
    summary = [ordered]@{
        passed = @($rows | Where-Object { $_.status -eq 'passed' }).Count
        failed = @($rows | Where-Object { $_.status -eq 'failed' }).Count
        total = $rows.Count
    }
    cases = $rows
}
[System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Output),
    ($record | ConvertTo-Json -Depth 12) + "`n", [System.Text.UTF8Encoding]::new($false))
$record.summary | ConvertTo-Json
if ($record.summary.failed -ne 0) { exit 1 }
