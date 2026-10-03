// CI on every commit; the nightly ops run fires from the cron trigger or
// when RUN_OPS is ticked. Credentials are looked up per environment, so the
// same pipeline serves dev, QA and prod.
pipeline {
  agent any
  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }
  triggers { cron('H 2 * * *') }   // timer runs use the first TARGET_ENV choice; use one job per environment in practice
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

    stage('Nightly ops') {
      when { anyOf { triggeredBy 'TimerTrigger'; expression { return params.RUN_OPS } } }
      environment {
        BIOPS_ENV    = "${params.TARGET_ENV}"
        TABLEAU_URL  = credentials("tableau-url-${params.TARGET_ENV}")
        MSTR_URL     = credentials("mstr-url-${params.TARGET_ENV}")
        TABLEAU_PAT  = credentials("tableau-pat-${params.TARGET_ENV}")   // username/password -> _USR / _PSW
        MSTR_SVC     = credentials("mstr-svc-${params.TARGET_ENV}")
      }
      steps {
        sh '''
          run() {
            docker run --rm -v biops-data:/data \
              -e BIOPS_ENV -e TABLEAU_URL -e MSTR_URL \
              -e TABLEAU_PAT_NAME="$TABLEAU_PAT_USR" -e TABLEAU_PAT_SECRET="$TABLEAU_PAT_PSW" \
              -e MSTR_USER="$MSTR_SVC_USR" -e MSTR_PASSWORD="$MSTR_SVC_PSW" \
              "$IMAGE" "$@"
          }
          run health      # fails the build (and alerts) before anything else runs
          run collect
          run backup
          run refresh
        '''
      }
    }
  }

  post {
    failure { echo "BI ops pipeline failed for ${params.TARGET_ENV}. Wire this to Slack or email." }
    always  { sh 'rm -rf smoke.db smoke-backups' }
  }
}
