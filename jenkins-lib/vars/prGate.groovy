import edu.hm.hafner.coverage.Metric
import io.jenkins.plugins.coverage.metrics.model.Baseline
import io.jenkins.plugins.coverage.metrics.steps.CoverageBuildAction

/**
 * prGate v1: publish and enforce unit tests, line coverage and one static
 * analysis gate. Report paths, labels and thresholds are supplied by the
 * caller, so the step contains no application-specific names.
 */
def call(Map config = [:]) {
    def testPattern = config.testResults ?: '**/target/surefire-reports/*.xml'
    def coveragePattern = config.coverageReport ?: '**/target/jacoco-ut/jacoco.xml'
    def coverageParser = config.coverageParser ?: 'JACOCO'
    def coverageScm = config.coverageScm ?: null
    def coverageThreshold = config.coverageThreshold != null ? (config.coverageThreshold as double) : 0.0d
    def modifiedLinesThreshold = config.modifiedLinesThreshold != null ? (config.modifiedLinesThreshold as double) : 0.0d
    def staticToolName = config.staticAnalysisTool ?: 'pmd'
    def staticPattern = config.staticAnalysisReport ?: '**/target/pmd.xml'
    def staticNewThreshold = config.staticNewIssueThreshold != null ? (config.staticNewIssueThreshold as int) : 1
    def enforce = config.enforce != null ? (config.enforce as boolean) : true
    def summaryFile = config.summaryFile ?: 'prgate-summary.md'
    def mavenExit = config.mavenExit != null ? (config.mavenExit as int) : null
    def scopeLabel = config.scopeLabel ?: 'unspecified'
    def revision = config.revision ?: 'unknown'
    def referenceCommit = config.referenceCommit ?: null
    def referenceJob = config.referenceJob ?: null

    def failures = []
    def notes = []

    // Unit tests: always enforced. An empty test inventory is never a pass.
    def testState = 'FAIL'
    def testTotal = 0
    def testFailed = 0
    def testSkipped = 0
    try {
        def testResult = junit testResults: testPattern, allowEmptyResults: true
        testTotal = testResult?.getTotalCount() ?: 0
        testFailed = testResult?.getFailCount() ?: 0
        testSkipped = testResult?.getSkipCount() ?: 0
        if (testTotal > 0 && testFailed == 0) {
            testState = 'PASS'
        }
    } catch (Exception e) {
        notes << "junit step: ${e.message}"
    }
    if (testState != 'PASS') {
        failures << "unit tests: ${testTotal} run, ${testFailed} failed, ${testSkipped} skipped"
    }
    def testsFailed = testState != 'PASS'

    // Coverage: project line coverage gate, plus an optional modified-lines gate.
    // Both gates are evaluated independently. The modified-lines gate is off by
    // default (threshold 0) so existing callers keep their exact behavior.
    def coverageState = 'FAIL'
    def coverageLine = null
    def wantProject = enforce && coverageThreshold > 0.0d
    def wantModified = enforce && modifiedLinesThreshold > 0.0d
    def modifiedState = wantModified ? 'FAIL' : 'DISABLED'
    def modifiedLine = null
    def modifiedNoLines = false
    def coverageGates = []
    if (wantProject) {
        coverageGates << [threshold: coverageThreshold, metric: 'LINE',
                          baseline: 'PROJECT', criticality: 'FAILURE']
    }
    if (wantModified) {
        coverageGates << [threshold: modifiedLinesThreshold, metric: 'LINE',
                          baseline: 'MODIFIED_LINES', criticality: 'FAILURE']
    }
    try {
        def coverageArgs = [
            tools: [[parser: coverageParser, pattern: coveragePattern]],
            id: 'coverage',
            name: 'Coverage',
            enabledForFailure: true,
            failOnError: false,
            sourceCodeRetention: 'NEVER'
        ]
        if (coverageGates) {
            coverageArgs.qualityGates = coverageGates
        }
        if (coverageScm) {
            coverageArgs.scm = coverageScm
        }
        recordCoverage(coverageArgs)

        def action = currentBuild.rawBuild.getAction(CoverageBuildAction)
        if (action != null && action.getStatistics() != null
                && action.getStatistics().containsValue(Metric.LINE)) {
            coverageLine = action.getStatistics().roundValue(Metric.LINE)
        }
        if (!enforce || coverageThreshold <= 0.0d) {
            coverageState = (coverageLine != null) ? 'PUBLISHED' : 'FAIL'
        } else if (coverageLine != null && coverageLine >= coverageThreshold) {
            coverageState = 'PASS'
        }
        if (coverageLine == null) {
            coverageState = testsFailed ? 'NOT EVALUATED' : 'FAIL'
            notes << "no line coverage report or value available; the build may have stopped before JaCoCo wrote it"
        }

        if (wantModified) {
            def hasReference = false
            def deltaFailed = false
            def changeSet = null
            if (action != null) {
                def reference = action.getReferenceBuild()
                hasReference = reference != null && reference.isPresent()
                changeSet = action.getChangeSet()
                def coverageLog = action.getLog()
                deltaFailed = coverageLog != null && coverageLog.hasErrors()
                def modifiedValue = action.getValueForMetric(Baseline.MODIFIED_LINES, Metric.LINE)
                if (modifiedValue != null && modifiedValue.isPresent()) {
                    modifiedLine = modifiedValue.get().asRounded()
                }
            }
            if (hasReference && !deltaFailed && changeSet != null
                    && !changeSet.hasModifiedLines()) {
                // No executable Java line changed in this build. This is a real
                // result, not missing data: a reference build exists and the
                // code delta computed without errors.
                modifiedState = 'PASS'
                modifiedNoLines = true
            } else if (modifiedLine == null) {
                modifiedState = testsFailed ? 'NOT EVALUATED' : 'FAIL'
                notes << (deltaFailed
                    ? "modified-lines coverage could not be computed; the coverage log reported code delta errors"
                    : "no modified-lines coverage value available; the reference build, coverage report or code delta is missing")
            } else if (modifiedLine >= modifiedLinesThreshold) {
                modifiedState = 'PASS'
            } else {
                modifiedState = 'FAIL'
            }
        }
        action = null
    } catch (Exception e) {
        notes << "coverage step: ${e.message}"
    }
    if (coverageState == 'FAIL') {
        failures << "coverage: project line below ${coverageThreshold}%"
    }
    if (wantModified && modifiedState == 'FAIL') {
        failures << "coverage: modified lines below ${modifiedLinesThreshold}%"
    }

    // One static-analysis gate. Only new issues block; inherited issues stay visible.
    // The plugin fails when the count is at or above the threshold, so 1 means
    // that any new issue blocks. A value of 0 would make the gate inactive.
    if (enforce && staticNewThreshold < 1) {
        throw new IllegalArgumentException('staticNewIssueThreshold must be at least 1')
    }
    def staticState = 'FAIL'
    def staticTotal = null
    def staticNew = null
    def referenceName = null
    def referenceFullName = null
    def cleanReferenceFound = true
    def staticTool = null
    switch (staticToolName) {
        case 'pmd':
            staticTool = pmdParser(pattern: staticPattern)
            break
        case 'checkstyle':
            staticTool = checkStyle(pattern: staticPattern)
            break
        case 'spotbugs':
            staticTool = spotBugs(pattern: staticPattern)
            break
        default:
            throw new IllegalArgumentException("Unsupported staticAnalysisTool: ${staticToolName}")
    }

    if (!(staticPattern ==~ /[A-Za-z0-9._*\/-]+/)) {
        throw new IllegalArgumentException('staticAnalysisReport must be a simple path or glob')
    }

    def staticPresent = fileExists(file: staticPattern)
    if (!staticPresent && staticPattern.contains('*')) {
        staticPresent = sh(returnStatus: true,
                           script: "ls ${staticPattern} > /dev/null 2>&1") == 0
    }
    try {
        if (staticPresent) {
            def results
            if (enforce) {
                if (referenceJob) {
                    discoverReferenceBuild(referenceJob: referenceJob,
                                           requiredResult: 'SUCCESS')
                } else {
                    discoverReferenceBuild()
                }
            }
            def issueArgs = [
                tool: staticTool,
                id: staticToolName,
                name: "${staticToolName.toUpperCase()} issues",
                enabledForFailure: true,
                failOnError: false,
                skipBlames: true
            ]
            if (enforce) {
                issueArgs.qualityGates = [[threshold: staticNewThreshold,
                                           type: 'NEW', criticality: 'FAILURE']]
            }
            if (coverageScm) {
                issueArgs.scm = coverageScm
            }
            results = recordIssues(issueArgs)

            if (results != null && !results.isEmpty()) {
                staticTotal = 0
                staticNew = 0
                results.each { result ->
                    staticTotal += result.getTotalSize()
                    staticNew += result.getNewSize()
                    def reference = result.getReferenceBuild()
                    if (reference != null && reference.isPresent() && referenceName == null) {
                        def referenceRun = reference.get()
                        referenceName = referenceRun.getDisplayName()
                        referenceFullName = referenceRun.getParent().getFullName()
                        referenceRun = null
                    }
                }
            }
            results = null
            if (enforce && referenceJob &&
                    (referenceName == null || referenceFullName != referenceJob)) {
                cleanReferenceFound = false
            }
            if (!enforce) {
                staticState = (staticTotal != null) ? 'PUBLISHED' : 'FAIL'
            } else if (!cleanReferenceFound) {
                staticState = 'FAIL'
                notes << "no clean reference build found for ${referenceCommit}"
            } else if (staticTotal != null && staticNew < staticNewThreshold) {
                staticState = 'PASS'
            }
            if (staticTotal == null) {
                notes << "no ${staticToolName} issue value parsed from ${staticPattern}"
            }
        } else {
            staticState = testsFailed ? 'NOT EVALUATED' : 'FAIL'
            notes << "no static-analysis report at ${staticPattern}; the build may have stopped before PMD wrote it"
        }
    } catch (Exception e) {
        notes << "static analysis step: ${e.message}"
    }
    if (staticState == 'FAIL') {
        failures << (cleanReferenceFound
            ? "${staticToolName}: new issues at or above ${staticNewThreshold}"
            : "${staticToolName}: no clean reference build for ${referenceCommit}")
    }

    if (mavenExit != null && mavenExit != 0) {
        failures << "maven: exit ${mavenExit}"
    }

    def decision = failures.isEmpty() ? 'PASS' : (enforce ? 'BLOCK' : 'OBSERVE')
    def buildUrl = currentBuild.absoluteUrl
    def coverageValue = coverageLine != null ? String.format('%.2f%%', coverageLine) : 'not parsed'
    def modifiedValue = modifiedNoLines ? 'no modified lines'
        : (modifiedLine != null ? String.format('%.2f%%', modifiedLine) : 'not available')
    def staticSummary = staticTotal != null ? "${staticTotal} total, ${staticNew} new" : 'not parsed'
    def lines = [
        '# prGate v1',
        '',
        "- Scope: ${scopeLabel}",
        "- Revision: ${revision}",
        "- Build: ${buildUrl}",
        "- Enforce: ${enforce}",
        mavenExit != null ? "- Maven exit: ${mavenExit}" : '- Maven exit: not supplied',
        "- Unit tests: ${testTotal} run, ${testFailed} failed, ${testSkipped} skipped -> ${testState}",
        "- Coverage (${coverageParser} line, project, threshold ${coverageThreshold}%): ${coverageState} (${coverageValue})",
        "  Report: ${buildUrl}coverage/",
        wantModified ? "- Coverage (${coverageParser} line, modified lines, threshold ${modifiedLinesThreshold}%): ${modifiedState} (${modifiedValue})" : null,
        wantModified ? "  Report: ${buildUrl}coverage/" : null,
        "- Static analysis (${staticToolName}, NEW threshold ${staticNewThreshold}): ${staticState} (${staticSummary})",
        "  Report: ${buildUrl}${staticToolName}/",
        referenceName != null ? "- Static reference build: ${referenceName}" : '- Static reference build: none',
        referenceJob != null ? "- Static reference job: ${referenceJob}" : '- Static reference job: not configured',
        referenceCommit != null ? "- Pinned reference commit: ${referenceCommit}" : '- Pinned reference commit: not configured',
        '- Inherited static issues remain visible; only new issues block.',
        "- Decision: ${decision}"
    ].findAll { line -> line != null }
    notes.each { note -> lines << "- Note: ${note}" }
    lines << ''

    writeFile file: summaryFile, text: lines.join('\n')
    archiveArtifacts artifacts: summaryFile, allowEmptyArchive: false
    lines.each { line -> echo line }

    if (enforce && decision == 'BLOCK') {
        error("prGate blocked: ${failures.join('; ')}")
    }
}
