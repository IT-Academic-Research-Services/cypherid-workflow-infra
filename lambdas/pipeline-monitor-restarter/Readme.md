This app is a temporary solution to the reliability issues in the
[Pipeline Monitor](https://github.com/chanzuckerberg/idseq-web/blob/prod/lib/tasks/pipeline_monitor.rake).
It runs the equivalent of the following commands every 50 minutes:

- `aws ecs update-service --force-new-deployment --service idseq-staging-resque-pipeline-monitor --cluster staging`
- `aws ecs update-service --force-new-deployment --service idseq-prod-resque-pipeline-monitor --cluster prod`

To deploy the app in the `idseq-dev` account, run `make deploy` in the parent directory.

This app will be retired after the async event handling system replaces the singleton pipeline monitor loop.
