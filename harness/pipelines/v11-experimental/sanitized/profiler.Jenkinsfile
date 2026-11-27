// Sanitized reproduction copy of the Gate 3A experimental definition.
// Historical execution used absolute /spike and /logs paths. These copies
// substitute ${SPIKE_ROOT} and ${EVIDENCE_ROOT}. They were not rerun.
pipeline {
  agent { label 'jdk11-experimental' }
  options { disableConcurrentBuilds() }
  stages {
    stage('profiler') {
      steps {
        sh '''
          set -eu
          EV=${EVIDENCE_ROOT}/gate3a/profiler-$BUILD_NUMBER
          mkdir -p "$EV"
          JAR=${SPIKE_ROOT}/tools/maven-profiler-3.3-shaded.jar
          echo "d235bc3f1d75d3eefde5627f33e7255c3d2f4476bad7f3c60fed6056a54f6f87  $JAR" | sha256sum -c -
          cd ${SPIKE_ROOT}/profiler3
          git rev-parse HEAD > "$EV/head.txt"
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -B -T 2 -fae \
            -Dmaven.test.failure.ignore=true \
            -Dmaven.repo.local=${SPIKE_ROOT}/m2-gib-verify \
            -Dprofile -DprofileFormat=JSON \
            -Dmaven-profiler-report-directory="$EV/profiler-report" \
            -Dmaven.ext.class.path="$JAR" verify > "$EV/maven.log" 2>&1
          cp -a "$EV/profiler-report"/*.json "$EV/" 2>/dev/null || true
          tail -n 20 "$EV/maven.log"
          echo "GATE3A_PROFILER_OK"
        '''
      }
    }
  }
}
