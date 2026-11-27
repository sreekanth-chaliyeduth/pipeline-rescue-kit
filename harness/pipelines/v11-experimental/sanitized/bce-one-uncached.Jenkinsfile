// Sanitized reproduction copy of the Gate 3A experimental definition.
// Historical execution used absolute /spike and /logs paths. These copies
// substitute ${SPIKE_ROOT} and ${EVIDENCE_ROOT}. They were not rerun.
pipeline {
  agent { label 'jdk11-experimental' }
  options { disableConcurrentBuilds() }
  stages {
    stage('one-test-uncached') {
      steps {
        sh '''
          set -eu
          EV=${EVIDENCE_ROOT}/gate3a/bce-one-uncached-$BUILD_NUMBER
          mkdir -p "$EV"
          cd ${SPIKE_ROOT}/bce-one
          git checkout -q bce-one
          git rev-parse HEAD > "$EV/head.txt"
          set +e
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -T 2 -fae \
            -Dmaven.repo.local=${SPIKE_ROOT}/m2-gib-verify \
            -Dmaven.build.cache.enabled=false verify > "$EV/maven.log" 2>&1
          RC=$?
          set -e
          cp -a ts-basic-service/target/surefire-reports "$EV/" 2>/dev/null || true
          grep -n "BasicControllerTest.testHome" "$EV/maven.log" || true
          tail -n 20 "$EV/maven.log"
          echo "GATE3A_BCE_ONE_UNCACHED_RC=$RC"
          exit $RC
        '''
      }
    }
  }
}
