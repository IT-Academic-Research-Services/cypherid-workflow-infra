# type: ignore

import functools
import os

import pymysql

from chalicelib import config


@functools.lru_cache(maxsize=None)
def conn():
    params = config.get_parameters()

    if "LOCAL_MODE" in os.environ:
        # in local mode, passing a password parameter (even None)
        # will cause the connection to fail
        return pymysql.connect(
            host=params["MYSQL_HOST"],
            port=int(params["MYSQL_PORT"]),
            user=params["MYSQL_USERNAME"],
            db=params["MYSQL_DB"],
            connect_timeout=10,
        )
    else:
        return pymysql.connect(
            host=params["MYSQL_HOST"],
            port=int(params["MYSQL_PORT"]),
            user=params["MYSQL_USERNAME"],
            passwd=params["MYSQL_PASSWORD"],
            db=params["MYSQL_DB"],
            ssl={"enable_tls": True},
            connect_timeout=10,
        )


def get_all_mysql_pipeline_run_ids():
    with conn().cursor(pymysql.cursors.SSDictCursor) as cursor:
        cursor.execute("""SELECT id FROM pipeline_runs""")
        return [row["id"] for row in cursor.fetchall()]
