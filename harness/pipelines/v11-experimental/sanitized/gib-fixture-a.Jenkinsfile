// Sanitized reproduction copy of the Gate 3A experimental definition.
// Historical execution used absolute /spike and /logs paths. These copies
// substitute ${SPIKE_ROOT} and ${EVIDENCE_ROOT}. They were not rerun.
pipeline {
  agent { label 'jdk11-experimental' }
  options { disableConcurrentBuilds() }
  stages {
    stage('gib-fixture-a') {
      steps {
        sh '''
          set -eu
          EV=${EVIDENCE_ROOT}/gate3a/gib-a-$BUILD_NUMBER
          mkdir -p "$EV"
          cd ${SPIKE_ROOT}/work/gib
          git checkout -q fixture-a
          rm -f gib-a-iso.txt
          git rev-parse HEAD > "$EV/head.txt"
          git diff --name-only gib-base..HEAD > "$EV/diff.txt"
          set +e
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -o -T 2 -fae \
            -Dmaven.test.failure.ignore=true \
            -Dmaven.repo.local=${SPIKE_ROOT}/work/m2-gib-verify \
            -Dgib.referenceBranch=refs/heads/gib-base \
            -Dgib.logImpactedTo="$EV/impacted.txt" verify > "$EV/maven.log" 2>&1
          RC=$?
          set -e
          cp -a ts-order-service/target/surefire-reports "$EV/" 2>/dev/null || true
          cat "$EV/maven.log"
          echo "GATE3A_GIB_A_RC=$RC"
          exit $RC
        '''
      }
    }
  }
}
