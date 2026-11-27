// Sanitized reproduction copy of the Gate 3A experimental definition.
// Historical execution used absolute /spike and /logs paths. These copies
// substitute ${SPIKE_ROOT} and ${EVIDENCE_ROOT}. They were not rerun.
pipeline {
  agent { label 'jdk11-experimental' }
  options { disableConcurrentBuilds() }
  stages {
    stage('environment') {
      steps {
        sh '''
          set -eu
          echo "GATE3A_SMOKE build=$BUILD_NUMBER"
          JAVA_HOME=/opt/java/jdk11 /opt/maven/bin/mvn -v
          /opt/java/jdk11/bin/java -version
          git --version
          ls -1 ${SPIKE_ROOT} | head -n 5
          ls -1 /repo/harness/pipelines/v11-experimental
        '''
      }
    }
  }
}
