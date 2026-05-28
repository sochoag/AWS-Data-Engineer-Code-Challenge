"""
glue_transform.py — Glue Job #1
Single responsibility: transform raw data and write it to curated/.

Flow:
  s3://bucket/raw/battery14_df.csv  ─┐
                                      ├─ filter → join → map gender → Parquet
  s3://bucket/raw/degrees.csv       ─┘
                                      └─▶  s3://bucket/curated/year=.../month=.../day=.../

Filters (passed dynamically from Lambda via Step Function):
  - gender          == filterGender  (default: 'f')
  - age             >  filterAgeMin  (default: 30)
  - country         == filterCountry (default: 'US')
  - education_level >  filterEducationMin (default: 6 — Master's degree)
  - raw_score       >  filterRawScoreMin  (default: 300)

Transformations:
  - gender code mapped to full label: 'f' → 'Female', 'm' → 'Male'
  - left join with degrees.csv on education_level → adds 'description' column
"""

import sys
from datetime import datetime

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType

# ── Initialization ────────────────────────────────────────────────────────────
args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "RAW_BUCKET",
        "RAW_KEY",
        "DEGREES_KEY",
        "CURATED_PREFIX",
        "EXECUTION_DATE",
        # Dynamic filters — controlled from Lambda via Step Function
        "FILTER_GENDER",
        "FILTER_AGE_MIN",
        "FILTER_COUNTRY",
        "FILTER_EDUCATION_MIN",
        "FILTER_RAW_SCORE_MIN",
    ],
)

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

logger = glueContext.get_logger()

raw_bucket     = args["RAW_BUCKET"]
raw_key        = args["RAW_KEY"]
degrees_key    = args["DEGREES_KEY"]
curated_prefix = args["CURATED_PREFIX"]
execution_date = args["EXECUTION_DATE"]

# Dynamic filters — passed from Lambda via Step Function (no hardcoding)
filter_gender        = args["FILTER_GENDER"]                    # 'f' | 'm'
filter_age_min       = float(args["FILTER_AGE_MIN"])            # e.g. 30.0
filter_country       = args["FILTER_COUNTRY"]                   # e.g. 'US'
filter_education_min = float(args["FILTER_EDUCATION_MIN"])      # e.g. 6.0
filter_raw_score_min = float(args["FILTER_RAW_SCORE_MIN"])      # e.g. 300.0

# Map gender codes to full labels
GENDER_MAP = {"f": "Female", "m": "Male"}
gender_label = GENDER_MAP.get(filter_gender, filter_gender.capitalize())

logger.info(
    f"=== Glue Transform Job started | execution_date={execution_date} | "
    f"filters: gender={filter_gender}, age>{filter_age_min}, country={filter_country}, "
    f"education>{filter_education_min}, raw_score>{filter_raw_score_min} ==="
)

# ── Read ──────────────────────────────────────────────────────────────────────
battery_path = f"s3://{raw_bucket}/{raw_key}"
degrees_path = f"s3://{raw_bucket}/{degrees_key}"

logger.info(f"Reading battery data from: {battery_path}")
battery_df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(battery_path)
)

logger.info(f"Reading degrees from: {degrees_path}")
degrees_df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(degrees_path)
)

logger.info(f"Original record count: {battery_df.count()}")

# ── Dynamic filtering ─────────────────────────────────────────────────────────
# Parameters come from Lambda via Step Function — no hardcoding.
# Nulls in float64 columns are excluded automatically (null > N evaluates to false).
filtered_df = battery_df.filter(
    (F.col("gender") == filter_gender)
    & (F.col("age") > filter_age_min)
    & (F.col("country") == filter_country)
    & (F.col("education_level") > filter_education_min)
    & (F.col("raw_score") > filter_raw_score_min)
)

count_after_filter = filtered_df.count()
logger.info(f"Record count after filtering: {count_after_filter}")

if count_after_filter == 0:
    logger.error("Filtering resulted in 0 records. Check the filter parameters.")
    raise ValueError("No records match the applied filters. Job aborted.")

# ── Data Quality Checks ───────────────────────────────────────────────────────
# Validates invariants that MUST hold after filtering.
# Any failure raises DataQualityError and aborts the job — bad data must never
# reach the curated zone.

class DataQualityError(Exception):
    """Raised when a post-filter data quality invariant is violated."""


def _dq_assert(condition: bool, message: str) -> None:
    """Fail fast: raise DataQualityError if condition is False."""
    if not condition:
        logger.error(f"DATA QUALITY FAILURE: {message}")
        raise DataQualityError(message)


logger.info("=== Running data quality checks ===")

# 1. No nulls in key columns
KEY_COLUMNS = ["gender", "age", "country", "education_level", "raw_score"]
for col_name in KEY_COLUMNS:
    null_count = filtered_df.filter(F.col(col_name).isNull()).count()
    _dq_assert(
        null_count == 0,
        f"Column '{col_name}' has {null_count} null value(s) after filtering.",
    )
    logger.info(f"  [PASS] No nulls in '{col_name}'")

# 2. Gender purity — every row must match the requested gender code
wrong_gender_count = filtered_df.filter(F.col("gender") != filter_gender).count()
_dq_assert(
    wrong_gender_count == 0,
    f"Found {wrong_gender_count} row(s) with gender != '{filter_gender}'.",
)
logger.info(f"  [PASS] All rows have gender == '{filter_gender}'")

# 3. Age floor — minimum age must be strictly above the filter threshold
min_age = filtered_df.agg(F.min("age")).collect()[0][0]
_dq_assert(
    min_age > filter_age_min,
    f"Minimum age {min_age} is not greater than filter threshold {filter_age_min}.",
)
logger.info(f"  [PASS] min(age)={min_age} > {filter_age_min}")

# 4. Country purity — every row must match the requested country
wrong_country_count = filtered_df.filter(F.col("country") != filter_country).count()
_dq_assert(
    wrong_country_count == 0,
    f"Found {wrong_country_count} row(s) with country != '{filter_country}'.",
)
logger.info(f"  [PASS] All rows have country == '{filter_country}'")

# 5. Education level floor
min_education = filtered_df.agg(F.min("education_level")).collect()[0][0]
_dq_assert(
    float(min_education) > filter_education_min,
    f"Minimum education_level {min_education} is not greater than {filter_education_min}.",
)
logger.info(f"  [PASS] min(education_level)={min_education} > {filter_education_min}")

# 6. Raw score floor
min_raw_score = filtered_df.agg(F.min("raw_score")).collect()[0][0]
_dq_assert(
    float(min_raw_score) > filter_raw_score_min,
    f"Minimum raw_score {min_raw_score} is not greater than {filter_raw_score_min}.",
)
logger.info(f"  [PASS] min(raw_score)={min_raw_score} > {filter_raw_score_min}")

logger.info(f"=== All data quality checks passed ({count_after_filter} records) ===")

# ── Transformations ───────────────────────────────────────────────────────────
# 1. Map gender code to full label using the dynamic map
filtered_df = filtered_df.withColumn(
    "gender",
    F.when(F.col("gender") == filter_gender, gender_label).otherwise(F.col("gender")),
)

# 2. Cast education_level to int for the join (it is float64 due to NaN values in the CSV)
filtered_df = filtered_df.withColumn(
    "_edu_int",
    F.col("education_level").cast(IntegerType()),
)

# ── Join with degrees ─────────────────────────────────────────────────────────
# Rename the join key in degrees to avoid column ambiguity after the join
degrees_renamed = degrees_df.withColumnRenamed("education_level", "_deg_level")

result_df = (
    filtered_df
    .join(degrees_renamed, filtered_df["_edu_int"] == degrees_renamed["_deg_level"], how="left")
    .drop("_edu_int", "_deg_level")
)

logger.info(f"Record count after join: {result_df.count()}")
logger.info(f"Final schema: {result_df.schema.simpleString()}")

# ── Write to curated/ ─────────────────────────────────────────────────────────
exec_dt     = datetime.strptime(execution_date, "%Y-%m-%d")
output_path = (
    f"s3://{raw_bucket}/{curated_prefix}"
    f"/year={exec_dt.year}"
    f"/month={exec_dt.month:02d}"
    f"/day={exec_dt.day:02d}/"
)

logger.info(f"Writing Parquet to: {output_path}")
(
    result_df
    .write
    .mode("overwrite")
    .parquet(output_path)
)

logger.info("=== Glue Transform Job completed successfully ===")
job.commit()
