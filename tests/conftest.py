"""
conftest.py — shared pytest fixtures.
"""
import os
import json
import pytest
import boto3
from moto import mock_aws


# ── AWS environment stubs (required by moto) ──────────────────────────────────
@pytest.fixture(autouse=True)
def aws_credentials():
    """Prevent any real AWS calls from leaking out of the test suite."""
    os.environ["AWS_ACCESS_KEY_ID"]     = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"]    = "testing"
    os.environ["AWS_SESSION_TOKEN"]     = "testing"
    os.environ["AWS_DEFAULT_REGION"]    = "us-east-1"


@pytest.fixture
def sfn_client():
    """Mocked Step Functions client (no real AWS calls)."""
    with mock_aws():
        yield boto3.client("stepfunctions", region_name="us-east-1")


@pytest.fixture
def state_machine_arn(sfn_client):
    """Creates a dummy state machine and returns its ARN."""
    response = sfn_client.create_state_machine(
        name="cc-de-etl-orchestrator",
        definition=json.dumps({"Comment": "test", "StartAt": "Done", "States": {"Done": {"Type": "Succeed"}}}),
        roleArn="arn:aws:iam::123456789012:role/test-role",
    )
    return response["stateMachineArn"]


@pytest.fixture
def lambda_env(state_machine_arn, monkeypatch):
    """Sets the environment variables the Lambda handler reads at runtime."""
    monkeypatch.setenv("STATE_MACHINE_ARN", state_machine_arn)
    monkeypatch.setenv("DATA_BUCKET",       "cc-data-engineer-123456789-us-east-1")
