"""
glue_iceberg.py — Glue Job #2
Single responsibility: read the transformed Parquet from curated/ and write it
as an Iceberg table registered in the Glue Data Catalog.

Flow:
  s3://bucket/curated/year=.../month=.../day=.../  ──▶  Iceberg table (Glue Catalog)
                                                         s3://bucket/iceberg/battery_filtered/

Job prerequisite:
  --datalake-formats iceberg   (enables Iceberg libraries in Glue 4.0)
"""

import sys
from datetime import datetime

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext

# ── Initialization ────────────────────────────────────────────────────────────
args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "DATA_BUCKET",
        "CURATED_PREFIX",
        "ICEBERG_PREFIX",
        "DATABASE_NAME",
        "TABLE_NAME",
        "EXECUTION_DATE",
    ],
)

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

logger = glueContext.get_logger()

data_bucket    = args["DATA_BUCKET"]
curated_prefix = args["CURATED_PREFIX"]
iceberg_prefix = args["ICEBERG_PREFIX"]
database_name  = args["DATABASE_NAME"]
table_name     = args["TABLE_NAME"]
execution_date = args["EXECUTION_DATE"]

logger.info(f"=== Glue Iceberg Job started | execution_date={execution_date} ===")

# ── Iceberg catalog configuration ─────────────────────────────────────────────
# Glue 4.0 with --datalake-formats iceberg loads the Iceberg extensions automatically.
# Here we only configure the catalog pointing to the Glue Data Catalog.
warehouse = f"s3://{data_bucket}/{iceberg_prefix}/"

spark.conf.set("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
spark.conf.set("spark.sql.catalog.glue_catalog.warehouse", warehouse)
spark.conf.set("spark.sql.catalog.glue_catalog.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
spark.conf.set("spark.sql.catalog.glue_catalog.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")

# ── Read curated Parquet ──────────────────────────────────────────────────────
exec_dt      = datetime.strptime(execution_date, "%Y-%m-%d")
curated_path = (
    f"s3://{data_bucket}/{curated_prefix}"
    f"/year={exec_dt.year}"
    f"/month={exec_dt.month:02d}"
    f"/day={exec_dt.day:02d}/"
)

logger.info(f"Reading Parquet from: {curated_path}")
curated_df = spark.read.parquet(curated_path)

record_count = curated_df.count()
logger.info(f"Records to write to Iceberg: {record_count}")

if record_count == 0:
    raise ValueError("No records found in curated/. Check the Transform job output.")

curated_df.createOrReplaceTempView("curated_data")

# ── Create Iceberg table if it does not exist ─────────────────────────────────
iceberg_table    = f"glue_catalog.{database_name}.{table_name}"
iceberg_location = f"s3://{data_bucket}/{iceberg_prefix}/{table_name}/"

logger.info(f"Target Iceberg table: {iceberg_table}")
logger.info(f"Location: {iceberg_location}")

# Build CREATE TABLE DDL dynamically from the inferred schema to avoid
# hardcoding column names (resilient to schema evolution).
fields_ddl = ",\n  ".join(
    f"`{field.name}` {field.dataType.simpleString().upper()}"
    for field in curated_df.schema.fields
)

create_sql = f"""
    CREATE TABLE IF NOT EXISTS {iceberg_table} (
      {fields_ddl}
    )
    USING iceberg
    LOCATION '{iceberg_location}'
    TBLPROPERTIES (
      'format-version' = '2',
      'write.format.default' = 'parquet'
    )
"""

logger.info("Running CREATE TABLE IF NOT EXISTS...")
spark.sql(create_sql)

# ── Write (INSERT OVERWRITE = full daily refresh) ─────────────────────────────
# For a daily pipeline over the same dataset, OVERWRITE is the correct strategy.
# For incremental append use cases, MERGE INTO would be preferred.
logger.info("Writing data to Iceberg table (INSERT OVERWRITE)...")
spark.sql(f"""
    INSERT OVERWRITE {iceberg_table}
    SELECT * FROM curated_data
""")

# ── Quick verification ────────────────────────────────────────────────────────
written_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {iceberg_table}").collect()[0]["cnt"]
logger.info(f"Records written to Iceberg table: {written_count}")

logger.info("=== Glue Iceberg Job completed successfully ===")
job.commit()
