#!/usr/bin/env bash
# =============================================================================
#  teardown_entrypoint.sh — Configura credenciales AWS y ejecuta el teardown
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()  { echo -e "${GREEN}✔  $*${RESET}"; }
die() { echo -e "${RED}✖  ERROR: $*${RESET}" >&2; exit 1; }

AWS_PROFILE="sam-deployer"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo -e "\n${CYAN}${BOLD}▶  Validating .env configuration${RESET}"

[[ -z "${AWS_ACCESS_KEY_ID:-}"     ]] && die "AWS_ACCESS_KEY_ID is not set in .env"
[[ -z "${AWS_SECRET_ACCESS_KEY:-}" ]] && die "AWS_SECRET_ACCESS_KEY is not set in .env"
[[ -z "${AWS_DEFAULT_REGION:-}"    ]] && die "AWS_DEFAULT_REGION is not set in .env"

ok "AWS variables loaded from .env"

# Escribe credenciales dentro del contenedor
mkdir -p /root/.aws

cat > /root/.aws/credentials <<EOF
[${AWS_PROFILE}]
aws_access_key_id = ${AWS_ACCESS_KEY_ID}
aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY}
EOF

cat > /root/.aws/config <<EOF
[profile ${AWS_PROFILE}]
region = ${REGION}
output = json
EOF

ok "Credentials successfull validated for '${AWS_PROFILE}'"

# Ejecuta el teardown (pedirá confirmación interactiva)
exec python3 scripts/teardown.py