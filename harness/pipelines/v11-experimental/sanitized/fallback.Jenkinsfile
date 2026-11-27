// Sanitized reproduction copy of the Gate 3A experimental definition.
// Historical execution used absolute /spike and /logs paths. These copies
// substitute ${SPIKE_ROOT} and ${EVIDENCE_ROOT}. They were not rerun.
pipeline {
  agent { label 'jdk11-experimental' }
  options { disableConcurrentBuilds() }
  stages {
    stage('fallback') {
      steps {
        sh '''
          set -eu
          EV=${EVIDENCE_ROOT}/gate3a/fallback-$BUILD_NUMBER
          mkdir -p "$EV"
          cd ${SPIKE_ROOT}/fallback
          git checkout -q fallback-base
          git rev-parse HEAD > "$EV/head.txt"
          set +e
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -o -T 2 -fae \
            -Dmaven.test.failure.ignore=true \
            -Dmaven.repo.local=${SPIKE_ROOT}/m2-gib-verify verify > "$EV/optimized.log" 2>&1
          RC1=$?
          set -e
          echo "GATE3A_OPTIMIZED_RC=$RC1"
          if grep -qE "Could not resolve|Cannot access central in offline mode|9.9.9" "$EV/optimized.log"; then
            echo "GATE3A_FALLBACK_REASON=extension-resolution"
            mv .mvn/extensions.xml .mvn/extensions.xml.disabled
            set +e
            JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -o -T 2 -fae \
              -Dmaven.repo.local=${SPIKE_ROOT}/m2-gib-verify verify > "$EV/fallback.log" 2>&1
            RC2=$?
            set -e
            grep -c "Building " "$EV/fallback.log" || true
            tail -n 15 "$EV/fallback.log"
            echo "GATE3A_FALLBACK_RC=$RC2"
            exit $RC2
          else
            echo "GATE3A_NOT_SETUP_FAILURE"
            tail -n 20 "$EV/optimized.log"
            exit $RC1
          fi
        '''
      }
    }
  }
}
