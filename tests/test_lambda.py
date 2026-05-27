"""
test_lambda.py
Unit tests for the Lambda starter function.

Coverage:
  - build_sfn_input(): parameter merging logic (no AWS calls needed)
  - lambda_handler():  end-to-end invocation with mocked Step Functions
"""
import json
import pytest
from unittest.mock import MagicMock
from moto import mock_aws

# Import the module under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda", "start_state_machine"))
from app import build_sfn_input, DEFAULTS, lambda_handler


# ══════════════════════════════════════════════════════════════════════════════
# build_sfn_input — pure logic, no AWS calls
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildSfnInput:

    DATA_BUCKET = "cc-data-engineer-123456789-us-east-1"

    def test_empty_event_uses_all_defaults(self):
        """An empty event must produce all default filter values."""
        result = build_sfn_input({}, self.DATA_BUCKET)

        assert result["rawBucket"]          == self.DATA_BUCKET
        assert result["rawKey"]             == DEFAULTS["rawKey"]
        assert result["degreesKey"]         == DEFAULTS["degreesKey"]
        assert result["filterGender"]       == "f"
        assert result["filterAgeMin"]       == "30"
        assert result["filterCountry"]      == "US"
        assert result["filterEducationMin"] == "6"
        assert result["filterRawScoreMin"]  == "300"
        assert result["databaseName"]       == "cc_data_engineer_db"
        assert result["tableName"]          == "battery_filtered"

    def test_execution_date_defaults_to_today(self):
        """executionDate must be set to today's UTC date when not provided."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = build_sfn_input({}, self.DATA_BUCKET)
        assert result["executionDate"] == today

    def test_execution_date_override(self):
        """executionDate provided in the event must override the default date."""
        result = build_sfn_input({"executionDate": "2026-01-15"}, self.DATA_BUCKET)
        assert result["executionDate"] == "2026-01-15"

    def test_gender_filter_override(self):
        """filterGender override must be applied and default 'f' must be replaced."""
        result = build_sfn_input({"filterGender": "m"}, self.DATA_BUCKET)
        assert result["filterGender"] == "m"

    def test_education_min_override(self):
        """filterEducationMin override must replace the default value of '6'."""
        result = build_sfn_input({"filterEducationMin": "4"}, self.DATA_BUCKET)
        assert result["filterEducationMin"] == "4"

    def test_multiple_overrides_applied_independently(self):
        """Multiple overrides must be applied without affecting non-overridden keys."""
        result = build_sfn_input(
            {
                "filterGender":       "m",
                "filterAgeMin":       "25",
                "filterRawScoreMin":  "150",
            },
            self.DATA_BUCKET,
        )
        assert result["filterGender"]       == "m"
        assert result["filterAgeMin"]       == "25"
        assert result["filterRawScoreMin"]  == "150"
        # Non-overridden keys must keep their defaults
        assert result["filterCountry"]      == "US"
        assert result["filterEducationMin"] == "6"

    def test_all_values_are_strings(self):
        """All values in the output must be strings (Glue job args requirement)."""
        result = build_sfn_input(
            {"filterAgeMin": 25, "filterRawScoreMin": 200},  # integers as input
            self.DATA_BUCKET,
        )
        for key, value in result.items():
            assert isinstance(value, str), f"Expected str for key '{key}', got {type(value)}"

    def test_raw_bucket_always_set(self):
        """rawBucket must always be set from the environment, not from the event."""
        result = build_sfn_input({}, self.DATA_BUCKET)
        assert result["rawBucket"] == self.DATA_BUCKET

    def test_unknown_event_keys_are_ignored(self):
        """Unknown keys in the event must not pollute the Step Function input."""
        result = build_sfn_input({"unknownKey": "value", "anotherRandom": 42}, self.DATA_BUCKET)
        assert "unknownKey"    not in result
        assert "anotherRandom" not in result


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — requires mocked Step Functions
# ══════════════════════════════════════════════════════════════════════════════

class TestLambdaHandler:

    @mock_aws
    def test_successful_invocation_returns_200(self, lambda_env, state_machine_arn):
        """A default invocation must return statusCode 200 with an executionArn."""
        context = MagicMock()
        context.aws_request_id = "test-request-id-12345678"

        response = lambda_handler({}, context)

        assert response["statusCode"]   == 200
        assert "executionArn"           in response
        assert "executionName"          in response
        assert "parameters"             in response

    @mock_aws
    def test_execution_name_contains_date(self, lambda_env, state_machine_arn):
        """Execution name must include the execution date for traceability."""
        context = MagicMock()
        context.aws_request_id = "abcdef12-1234-1234-1234-abcdef123456"

        response = lambda_handler({"executionDate": "2026-03-10"}, context)

        assert "2026-03-10" in response["executionName"]

    @mock_aws
    def test_parameters_reflect_overrides(self, lambda_env, state_machine_arn):
        """The 'parameters' field in the response must reflect applied overrides."""
        context = MagicMock()
        context.aws_request_id = "abcdef12-1234-1234-1234-abcdef123456"

        response = lambda_handler({"filterGender": "m", "filterAgeMin": "21"}, context)

        assert response["parameters"]["filterGender"] == "m"
        assert response["parameters"]["filterAgeMin"] == "21"

    @mock_aws
    def test_default_gender_filter_is_female(self, lambda_env, state_machine_arn):
        """When no override is provided, filterGender must default to 'f' (Female)."""
        context = MagicMock()
        context.aws_request_id = "abcdef12-1234-1234-1234-abcdef123456"

        response = lambda_handler({}, context)

        assert response["parameters"]["filterGender"] == "f"
