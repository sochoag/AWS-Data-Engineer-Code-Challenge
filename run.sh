#!/usr/bin/env bash
# =============================================================================
#  run.sh — Data Engineer Code Challenge · Full deployment & validation script
#
#  What this script does (in order):
#    1. Verifies required tools are installed
#    2. Installs Python test dependencies
#    3. Runs the unit test suite (pytest + moto)
#    4. Builds the SAM application (sam build)
#    5. Deploys the CloudFormation stack (sam deploy)
#    6. Uploads CSVs and Glue scripts to S3
#    7. Triggers the ETL pipeline via Lambda
#    8. Prints Athena queries to verify results
#
#  Prerequisites:
#    - AWS CLI v2 with a profile named "sam-deployer"
#    - SAM CLI (brew install aws-sam-cli  or  pip install aws-sam-cli)
#    - Python 3.9+
#    - data/battery14_df.csv present in the project root
#
#  Usage:
#    chmod +x run.sh
#    ./run.sh
#
#    Optional — skip deploy if the stack already exists:
#    SKIP_DEPLOY=1 ./run.sh
#
#    Optional — override notification email:
#    ALERT_EMAIL=you@example.com ./run.sh
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

step()  { echo -e "\n${CYAN}${BOLD}▶  $*${RESET}"; }
ok()    { echo -e "${GREEN}✔  $*${RESET}"; }
warn()  { echo -e "${YELLOW}⚠  $*${RESET}"; }
die()   { echo -e "${RED}✖  ERROR: $*${RESET}" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Configuration (override via env vars) ─────────────────────────────────────
AWS_PROFILE="${AWS_PROFILE:-sam-deployer}"
STACK_NAME="${STACK_NAME:-cc-data-engineer-etl}"
REGION="${REGION:-us-east-1}"
ALERT_EMAIL="${ALERT_EMAIL:-}"       # set to receive failure notifications
SKIP_DEPLOY="${SKIP_DEPLOY:-0}"

echo -e "\n${BOLD}╔══════════════════════════════════════════════════════════╗"
echo -e   "║   Data Engineer Code Challenge — ETL Pipeline Runner     ║"
echo -e   "╚══════════════════════════════════════════════════════════╝${RESET}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Prerequisites check
# ─────────────────────────────────────────────────────────────────────────────
step "Checking prerequisites"

command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.9+."
command -v pip3    >/dev/null 2>&1 || die "pip3 not found."
command -v aws     >/dev/null 2>&1 || die "AWS CLI not found. Install from https://aws.amazon.com/cli/"
command -v sam     >/dev/null 2>&1 || die "SAM CLI not found. Run: pip install aws-sam-cli"

ok "python3 $(python3 --version | awk '{print $2}')"
ok "AWS CLI $(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)"
ok "SAM CLI $(sam --version | awk '{print $NF}')"

# Verify AWS credentials
step "Verifying AWS credentials (profile: ${AWS_PROFILE})"
CALLER=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --region "$REGION" \
    --query 'Arn' --output text 2>&1) \
    || die "AWS credentials not working for profile '${AWS_PROFILE}'.\nRun: aws configure --profile ${AWS_PROFILE}"
ok "Authenticated as: ${CALLER}"

# Verify battery14_df.csv is present
if [[ ! -f "data/battery14_df.csv" ]]; then
    die "data/battery14_df.csv not found.\nPlace the file in ${SCRIPT_DIR}/data/ and re-run."
fi
ok "data/battery14_df.csv found"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Install Python test dependencies
# ─────────────────────────────────────────────────────────────────────────────
step "Installing Python test dependencies"
pip3 install -q -r requirements.txt
ok "Dependencies installed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Unit tests
# ─────────────────────────────────────────────────────────────────────────────
step "Running unit tests (pytest + moto)"
python3 -m pytest tests/ -v --tb=short \
    --cov=lambda/start_state_machine \
    --cov-report=term-missing \
    || die "Unit tests failed. Fix the failures before deploying."
ok "All tests passed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — SAM build
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_DEPLOY" == "1" ]]; then
    warn "SKIP_DEPLOY=1 — skipping sam build and sam deploy"
else
    step "Building SAM application (sam build)"
    sam build --profile "$AWS_PROFILE"
    ok "SAM build completed"

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5 — SAM deploy
    # ─────────────────────────────────────────────────────────────────────────
    step "Deploying CloudFormation stack: ${STACK_NAME}"

    DEPLOY_ARGS=(
        sam deploy
        --stack-name "$STACK_NAME"
        --region     "$REGION"
        --profile    "$AWS_PROFILE"
        --resolve-s3
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
        --no-confirm-changeset
        --no-fail-on-empty-changeset
    )

    if [[ -n "$ALERT_EMAIL" ]]; then
        DEPLOY_ARGS+=(--parameter-overrides "AlertEmail=${ALERT_EMAIL}")
        ok "Alert email set to: ${ALERT_EMAIL}"
    else
        warn "ALERT_EMAIL not set — CloudWatch alarm will deploy but notifications will go to the default in samconfig.toml"
        warn "To enable: ALERT_EMAIL=you@example.com ./run.sh"
    fi

    "${DEPLOY_ARGS[@]}"
    ok "Stack deployed successfully"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Upload data and scripts to S3
# ─────────────────────────────────────────────────────────────────────────────
step "Uploading data and Glue scripts to S3"
python3 scripts/upload_data.py
ok "Upload complete"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Trigger the ETL pipeline
# ─────────────────────────────────────────────────────────────────────────────
step "Triggering ETL pipeline via Lambda"

LAMBDA_NAME="cc-de-start-state-machine"
PAYLOAD='{"executionDate":"'"$(date -u +%Y-%m-%d)"'"}'

RESPONSE=$(aws lambda invoke \
    --function-name "$LAMBDA_NAME" \
    --payload        "$PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    --profile  "$AWS_PROFILE" \
    --region   "$REGION" \
    /tmp/lambda_response.json \
    --query    'StatusCode' \
    --output   text 2>&1)

if [[ "$RESPONSE" == "200" ]]; then
    EXECUTION_ARN=$(python3 -c "import json; d=json.load(open('/tmp/lambda_response.json')); print(d.get('executionArn','N/A'))")
    ok "Lambda invoked successfully"
    echo -e "    Execution ARN: ${CYAN}${EXECUTION_ARN}${RESET}"
else
    die "Lambda invocation failed (HTTP ${RESPONSE}). Check CloudWatch Logs."
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Verify: URLs and Athena queries
# ─────────────────────────────────────────────────────────────────────────────
ACCOUNT_ID=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text)
SFN_URL="https://${REGION}.console.aws.amazon.com/states/home?region=${REGION}#/executions/details/${EXECUTION_ARN}"
ATHENA_URL="https://${REGION}.console.aws.amazon.com/athena/home?region=${REGION}#/query-editor"

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Pipeline triggered — here is how to verify results      ${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${YELLOW}1. Monitor the Step Function execution (~3-5 min):${RESET}"
echo -e "   ${SFN_URL}"
echo ""
echo -e "${YELLOW}2. Once execution is SUCCEEDED, run these Athena queries:${RESET}"
echo -e "   Open: ${ATHENA_URL}"
echo ""
echo -e "   -- Check total record count (expected: 294)"
echo -e "   ${CYAN}SELECT COUNT(*) AS total FROM cc_data_engineer_db.battery_filtered;${RESET}"
echo ""
echo -e "   -- Confirm Iceberg table type"
echo -e "   ${CYAN}SHOW TBLPROPERTIES cc_data_engineer_db.battery_filtered;${RESET}"
echo ""
echo -e "   -- Spot-check the data"
echo -e "   ${CYAN}SELECT gender, country, MIN(age) AS min_age, MIN(raw_score) AS min_score"
echo -e "   FROM cc_data_engineer_db.battery_filtered"
echo -e "   GROUP BY gender, country;${RESET}"
echo ""
echo -e "${YELLOW}3. S3 Athena output bucket (set in Athena Settings if needed):${RESET}"
echo -e "   s3://cc-data-engineer-${ACCOUNT_ID}-${REGION}/athena/"
echo ""
echo -e "${GREEN}${BOLD}  All done! The full pipeline is running.${RESET}"
echo ""
