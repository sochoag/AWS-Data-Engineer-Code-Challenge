#!/usr/bin/env bash
# =============================================================================
#  teardown_entrypoint.sh — Writes AWS credentials inside the container and
#                           runs teardown.py to remove all AWS resources.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()  { echo -e "${GREEN}✔  $*${RESET}"; }
die() { echo -e "${RED}✖  ERROR: $*${RESET}" >&2; exit 1; }

AWS_PROFILE="sam-deployer"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# ─────────────────────────────────────────────────────────────────────────────
# Validate required variables from .env
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}▶  Validating .env configuration${RESET}"

[[ -z "${AWS_ACCESS_KEY_ID:-}"     ]] && die "AWS_ACCESS_KEY_ID is not set in .env"
[[ -z "${AWS_SECRET_ACCESS_KEY:-}" ]] && die "AWS_SECRET_ACCESS_KEY is not set in .env"
[[ -z "${AWS_DEFAULT_REGION:-}"    ]] && di