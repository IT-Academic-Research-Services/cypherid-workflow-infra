#!/usr/bin/env python3

# Using the Python Snowflake connector: https://docs.snowflake.com/en/user-guide/python-connector-example.html
# Snowflake keypair authentication: https://docs.snowflake.com/en/user-guide/key-pair-auth.html
# Generating a passwordless 2048-bit RSA PKCD #8 keypair:
#   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -nocrypt -out <NAME>.p8
# Extracting the public key:
#   openssl rsa -in <NAME>.p8 -pubout -out <NAME>.pub 
# Snowflake needs the private key to be unencrypted, so no real reason to generate it with an encryption pass phrase.
# The keypair should probably be stored in 1Pass, or whatever secure location the team prefers.

import os, sys
import snowflake.connector as sf
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)

account = os.environ["SNOWFLAKE_ACCOUNT"] # the subdomain before ".snowflakecomputing.com"
user = os.environ["SNOWFLAKE_USER"] # for production, we should create a service user...
role = os.environ["SNOWFLAKE_ROLE"] # ...and a minimally scoped role for that user
private_key = os.environ["SNOWFLAKE_PRIVATE_KEY"] # paste the whole PEM into github, headers/footers/line breaks included
warehouse = os.environ["SNOWFLAKE_WAREHOUSE"]
database = os.environ["SNOWFLAKE_DATABASE"]
schema = os.environ["SNOWFLAKE_SCHEMA"]

table = "IDSEQ_SHORT_READ_MNGS_BENCHMARKS"
stage = "dummy_data"
file = sys.argv[1]

private_key = load_pem_private_key(
    private_key.encode(),
    password=None,
    backend=default_backend(),
).private_bytes(
    encoding=Encoding.DER,
    format=PrivateFormat.PKCS8,
    encryption_algorithm=NoEncryption(),
)

connection = sf.connect(
    account=account,
    user=user,
    role=role,
    private_key=private_key,
    warehouse=warehouse,
    database=database,
    schema=schema,
)

cursor = connection.cursor()

dummy_data = """
version,index_version,sample,timestamp,wall_seconds,NT_aupr,NR_aupr
v1.2.3,2021-01-22,unambiguouslymapped_ds_hous1,2021-07-02T11:50:01.655693,999,0.9277058776814514,0.9610254513424724
v1.2.3,2021-01-22,unambiguouslymapped_ds_nycsm,2021-07-02T11:50:01.655693,999,0.8332097320545593,0.9254386690030195
v1.2.3,2021-01-22,unambiguouslymapped_ds_hous2,2021-07-02T11:50:01.655693,999,0.9828839459760512,1.0000000000000002
v1.2.3,2021-01-22,unambiguouslymapped_ds_gut,2021-07-02T11:50:01.655693,999,0.9907642500520077,1.0000000000000002
v1.2.3,2021-01-22,unambiguouslymapped_ds_buccal,2021-07-02T11:50:01.655693,999,1.0,1.0
v1.2.3,2021-01-22,idseq_bench_5,2021-07-02T11:50:01.655693,999,0.9999999999999998,0.9942941673710901
v1.2.3,2021-01-22,unambiguouslymapped_ds_cityparks,2021-07-02T11:50:01.655693,999,0.9710897204118143,0.9802068944105394
v1.2.3,2021-01-22,idseq_bench_3,2021-07-02T11:50:01.655693,999,1.0,1.0
v1.2.3,2021-01-22,unambiguouslymapped_ds_7,2021-07-02T11:50:01.655693,999,0.9584320459521608,0.9109415423771566
v1.2.3,2021-01-22,unambiguouslymapped_ds_soil,2021-07-02T11:50:01.655693,999,0.9600831389096869,0.9818208595218775
v1.2.3,2021-01-22,atcc_staggered,2021-07-02T11:50:01.655693,999,0.9863964906137896,0.7911311261316789
v1.2.3,2021-01-22,atcc_even,2021-07-02T11:50:01.655693,999,1.0000000000000002,1.0000000000000002
""".lstrip()
if file == "dummy_data.csv":
    with open(file, "w") as outfile:
        outfile.write(dummy_data)

# Snowflake best practices: identifiers in double quotes are case-sensitive
cursor.execute(f"USE DATABASE \"{database}\"")
cursor.execute(f"USE SCHEMA \"{schema}\"")
cursor.execute(f"CREATE TABLE IF NOT EXISTS \"{table}\" (version string, index_version string, \"sample\" string, timestamp datetime, wall_seconds integer, NT_aupr float, NR_aupr float)")
# there are table-scoped staging areas for Snowflake file-based imports: @"DATABASE"."SCHEMA".%"TABLE"/path
cursor.execute(f"PUT file://./{file} @%\"{table}\"/{stage} OVERWRITE = TRUE")
# import format options: https://docs.snowflake.com/en/sql-reference/sql/copy-into-table.html#format-type-options-formattypeoptions
cursor.execute(f"""
    COPY INTO \"{table}\"
    FROM @%\"{table}\"/{stage}
    FILE_FORMAT = ( TYPE = CSV, FIELD_DELIMITER = ',', SKIP_HEADER = 1, ERROR_ON_COLUMN_COUNT_MISMATCH = TRUE )
""")

print(f"Write result was: {connection.get_query_status(cursor.sfqid)}")
