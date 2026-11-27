// Sanitized reproduction copy of the Gate 3A experimental definition.
// Historical execution used absolute /spike and /logs paths. These copies
// substitute ${SPIKE_ROOT} and ${EVIDENCE_ROOT}. They were not rerun.
pipeline {
  agent { label 'jdk11-experimental' }
  options { disableConcurrentBuilds() }
  stages {
    stage('strict-gate') {
      steps {
        sh '''
          set -eu
          EV=${EVIDENCE_ROOT}/gate3a/bce-gate-$BUILD_NUMBER
          mkdir -p "$EV"
          cd ${SPIKE_ROOT}/bce
          git checkout -q bce-reconcile
          git rev-parse HEAD > "$EV/head.txt"
          set +e
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -T 2 -fae \
            -Dmaven.repo.local=${SPIKE_ROOT}/m2-gib-verify \
            -Dmaven.build.cache.enabled=true \
            -Dmaven.build.cache.location=${SPIKE_ROOT}/cache-gate verify > "$EV/maven.log" 2>&1
          RC=$?
          set -e
          cp -a */target/surefire-reports "$EV/" 2>/dev/null || true
          tail -n 25 "$EV/maven.log"
          echo "GATE3A_BCE_GATE_RC=$RC"
          exit $RC
        '''
      }
    }
  }
}
