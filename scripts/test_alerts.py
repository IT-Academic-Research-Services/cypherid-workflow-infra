#!/usr/bin/env python3

import os
import watchtower
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.addHandler(watchtower.CloudWatchLogHandler(log_group=f"ecs-logs-{os.environ['DEPLOYMENT_ENVIRONMENT']}"))
logger.info("subprocess.CalledProcessError: This is a test of the idseq log alert system. This is only a test.")
