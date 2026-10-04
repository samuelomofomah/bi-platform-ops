// CI on every build. Tick RUN_OPS to also run health, collect, backup and
// refresh against the chosen environment.
//
// GitHub Actions owns the nightly schedule, so this job has no timer: two
// schedulers would double every alert and every refresh.
//
// Jenkins credentials used (one pair per environment):
//   tableau-pat-<env>   "Username with password": PAT name / PAT secret
//   biops-env-<env>     "Secret file": KEY=value lines for everything else
//                       (TABLEAU_URL, TABLEAU_SITE, MSTR_URL, BIOPS_S3_BUCKET, ...)
pipeline {
  agent any
  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }
  parameters {
    choice(name: 'TARGET_ENV', choices: ['dev', 'qa', 'prod'], description: 'BI environment to operate on')
    booleanParam(name: 'RUN_OPS', defaultValue: false, description: 'Run health, collect, backup and refresh now')
  }
  environment {
    IMAGE = "bi-platform-ops:${env.BUILD_NUMBER}"
  }

  stages {
    stage('Lint and test') {
      steps {
        sh '''
          python3 -m venv .venv
          . .venv/bin/activate
          pip install -q -r requirements-dev.txt
          ruff check .
          bash -n scripts/linux_health.sh
          python -m unittest -v
        '''
      }
    }

    stage('Smoke test (mock)') {
      steps {
        sh '''
          . .venv/bin/activate
          export BIOPS_MOCK=1 BIOPS_DB=smoke.db BIOPS_BACKUP_DIR=smoke-backups
          python -m biops health
          python -m biops collect
          python -m biops backup
          python -m biops report
        '''
      }
    }

    stage('Build image') {
      steps { sh 'docker build -t "$IMAGE" .' }
    }

    stage('Ops run') {
      when { expression { return params.RUN_OPS } }
      environment {
        BIOPS_ENV = "${params.TARGET_ENV}"
      }
      steps {
        withCredentials([
          file(credentialsId: "biops-env-${params.TARGET_ENV}", variable: 'BIOPS_ENV_FILE'),
          usernamePassword(credentialsId: "tableau-pat-${params.TARGET_ENV}",
                           usernameVariable: 'TABLEAU_PAT_NAME', passwordVariable: 'TABLEAU_PAT_SECRET')
        ]) {
          sh '''
            run() {
              # --network host lets the container pick up the instance role for S3 and SNS.
              # The named volume keeps the database and backups between builds.
              docker run --rm --network host -v biops-data:/data \
                --env-file "$BIOPS_ENV_FILE" \
                -e BIOPS_ENV -e TABLEAU_PAT_NAME -e TABLEAU_PAT_SECRET \
                "$IMAGE" "$@"
            }
            status=0
            run health  || status=1   # a failed check alerts and turns the build red...
            run collect || status=1   # ...but whatever is reachable is still collected and backed up
            run backup  || status=1
            run refresh || status=1
            exit $status
          '''
        }
      }
    }
  }

  post {
    failure { echo "BI ops pipeline failed for ${params.TARGET_ENV}. Wire this to Slack or email." }
    always  { sh 'rm -rf smoke.db smoke-backups' }
  }
}
