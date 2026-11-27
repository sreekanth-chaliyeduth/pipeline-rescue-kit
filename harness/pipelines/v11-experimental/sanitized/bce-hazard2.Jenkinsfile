// Sanitized reproduction copy of the Gate 3A experimental definition.
// Historical execution used absolute /spike and /logs paths. These copies
// substitute ${SPIKE_ROOT} and ${EVIDENCE_ROOT}. They were not rerun.
pipeline {
  agent { label 'jdk11-experimental' }
  options { disableConcurrentBuilds() }
  stages {
    stage('seed') {
      steps {
        sh '''
          set -eu
          EV=${EVIDENCE_ROOT}/gate3a/bce-hazard2-$BUILD_NUMBER
          mkdir -p "$EV"
          cd ${SPIKE_ROOT}/bce
          git checkout -q bce-base
          rm -rf ${SPIKE_ROOT}/cache-hazard2
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -T 2 -fae \
            -Dmaven.test.failure.ignore=true \
            -Dmaven.repo.local=${SPIKE_ROOT}/m2-gib-verify \
            -Dmaven.build.cache.enabled=true \
            -Dmaven.build.cache.location=${SPIKE_ROOT}/cache-hazard2 verify > "$EV/seed.log" 2>&1
          echo "GATE3A_HAZARD_SEED_RC=$?"
        '''
      }
    }
    stage('strict-default-cached') {
      steps {
        sh '''
          set -eu
          EV=${EVIDENCE_ROOT}/gate3a/bce-hazard2-$BUILD_NUMBER
          cd ${SPIKE_ROOT}/bce
          set +e
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -T 2 -fae \
            -Dmaven.repo.local=${SPIKE_ROOT}/m2-gib-verify \
            -Dmaven.build.cache.enabled=true \
            -Dmaven.build.cache.location=${SPIKE_ROOT}/cache-hazard2 verify > "$EV/strict.log" 2>&1
          RC=$?
          set -e
          echo "restored=$(grep -c 'Found cached build, restoring' "$EV/strict.log" || true)"
          echo "tests=$(grep -c 'Tests run:' "$EV/strict.log" || true)"
          echo "GATE3A_HAZARD_STRICT_RC=$RC"
          tail -n 10 "$EV/strict.log"
          exit 0
        '''
      }
    }
  }
}
