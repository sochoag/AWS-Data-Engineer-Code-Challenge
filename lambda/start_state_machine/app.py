"""
Lambda starter — triggers the ETL Step Function.

Responsibility: build and adjust the State Machine input parameters before
starting the execution. Acts as the central control point for the pipeline:
any change in filters, paths or dates is managed here.

Flow:
  EventBridge (daily schedule) -> this Lambda -> Step Functions StartExecution
                                                  -> Glue Job #1 (applies filters)
                                                  -> Glue Job #2

Environment variables (set in template.yaml):
  STATE_MACHINE_ARN  -- ARN of the State Machine
  DATA_BUCKET        -- name of the main S3 bucket

Override parameters (all optional in the input event):

  Date / paths:
    executionDate   -- processing date (YYYY-MM-DD). Default: today UTC
    rawKey          -- S3 path to the main CSV file
    degreesKey      -- S3 path to the degrees CSV file

  Dataset filters (allow re-running with different criteria without
  modifying any Glue Job code):
    filterGender        -- gender code to include: 'f' | 'm'. Default: 'f'
    filterAgeMin        -- exclusive minimum age. Default: '30'
    filterCountry       -- country to filter. Default: 'US'
    filterEducationMin  -- exclusive minimum education level. Default: '6'
    filterRawScoreMin   -- exclusive minimum raw score. Default: '300'

Example -- reprocess only males with education > 4:
  {
    "filterGender": "m",
    "filterEducationMin": "4"
  }

Example -- backfill a specific date:
  {
    "executionDate": "2026-01-15"
  }
"""
import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -- Defaults ------------------------------------------------------------------
# All values are strings because Glue Job arguments are always strings.
DEFAULTS = {
    # S3 paths
    "rawKey":        "raw/battery14_df.csv",
    "degreesKey":    "raw/degrees.csv",
    "curatedPrefix": "curated",
    "icebergPrefix": "iceberg",
    # Glue Catalog
    "databaseName":  "cc_data_engineer_db",
    "tableName":     "battery_filtered",
    # Dataset filters
    "filterGender":       "f",    # 'f' = Female, 'm' = Male
    "filterAgeMin":       "30",   # age > filterAgeMin
    "filterCountry":      "US",
    "filterEducationMin": "6",    # education_level > filterEducationMin
    "filterRawScoreMin":  "300",  # raw_score > filterRawScoreMin
}

OVERRIDABLE_KEYS = list(DEFAULTS.keys()) + ["executionDate"]


def build_sfn_input(event: dict, data_bucket: str) -> dict:
    """
    Builds the Step Function input by merging defaults with any overrides
    coming from the event (EventBridge schedule or manual invocation).
    """
    default_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sfn_input = {**DEFAULTS}
    sfn_input["rawBucket"]     = data_bucket
    sfn_input["executionDate"] = event.get("executionDate", default_date)

    for key in OVERRIDABLE_KEYS:
        if key in event:
            logger.info("Override applied -- %s: '%s' -> '%s'",
                        key, sfn_input.get(key, "N/A"), event[key])
            sfn_input[key] = str(event[key])  # Glue args must always be strings

    return sfn_input


def lambda_handler(event, context):
    sfn_client        = boto3.client("stepfunctions")  # lazy init -- allows moto to mock it
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]
    data_bucket       = os.environ["DATA_BUCKET"]

    sfn_input      = build_sfn_input(event, data_bucket)
    execution_name = f"etl-{sfn_input['executionDate']}-{context.aws_request_id[:8]}"

    logger.info("Starting Step Function: %s", state_machine_arn)
    logger.info("Final input: %s", json.dumps(sfn_input))

    response = sfn_client.start_execution(
        stateMachineArn=state_machine_arn,
        name=execution_name,
        input=json.dumps(sfn_input),
    )

    logger.info("Execution started: %s", response["executionArn"])

    return {
        "statusCode":    200,
        "executionArn":  response["executionArn"],
        "executionName": execution_name,
        "parameters":    sfn_input,
    }
