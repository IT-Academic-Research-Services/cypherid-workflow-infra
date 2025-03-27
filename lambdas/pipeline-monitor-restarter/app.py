import os
import logging
import boto3
from chalice import Chalice, Rate

app = Chalice(app_name="idseq-pipeline-monitor-restarter")
app.log.setLevel(logging.INFO)

ecs = boto3.client("ecs")


@app.schedule(
    Rate(50, unit=Rate.MINUTES),
    name=f"idseq-{os.environ['DEPLOYMENT_ENVIRONMENT']}-restart-pipeline-monitor",
)
def restart_monitor(event):
    cluster = os.environ["DEPLOYMENT_ENVIRONMENT"]
    if os.environ["DEPLOYMENT_ENVIRONMENT"] == "prod":
        cluster = "idseq-prod-ecs"
    if os.environ["DEPLOYMENT_ENVIRONMENT"] in {"staging", "prod"}:
        service = (
            f"idseq-{os.environ['DEPLOYMENT_ENVIRONMENT']}-resque-pipeline-monitor"
        )
        app.log.info("Restarting %s", service)
        ecs.update_service(cluster=cluster, service=service, forceNewDeployment=True)
