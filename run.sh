#!/usr/bin/env bash
# =============================================================================
#  run.sh — Data Engineer Code Challenge · ETL Pipeline Runner
#
#  Diseñado para correr DENTRO del contenedor levantado por docker-compose.
#  No ejecutes este script directamente en el host — usa:
#
#      docker compose up --build
#
#  Flujo:
#    1. Verifica prerrequisitos (python3, aws, sam)
#    2. Valida credenciales AWS
#    3. Instala dependencias Python
#    4. Corre tests unitarios (pytest + moto)
#    5. sam build  (--no-use-container: ya estamos en Python 3.11)
#    6. sam deploy
#    7. Sube datos y scripts Glue a S3
#    8. Invoca la Lambda para iniciar el ETL
#    9. Imprime URLs y queries Athena para verificar resultados
#
#  Variables de entorno (inyectadas por docker-compose.yml):
#    AWS_PROFILE, STACK_NAME, REGION, ALERT_EMAIL, SKIP_DEPLOY
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

step() { echo -e "\n${CYAN}${BOLD}▶  $*${RESET}"; }
ok()   { echo -e "${GREEN}✔  $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠  $*${RESET}"; }
die()  { echo -e "${RED}✖  ERROR: $*${RESET}" >&2; exit 1; }

# Mueve al directorio donde vive el script
cd "$(dirname "$0")"

# ── Configuración (sobreescribible con env vars) ───────────────────────────────
AWS_PROFILE="${AWS_PROFILE:-sam-deployer}"
STACK_NAME="${STACK_NAME:-cc-data-engineer-etl}"
REGION="${REGION:-us-east-1}"
ALERT_EMAIL="${ALERT_EMAIL:-}"
SKIP_DEPLOY="${SKIP_DEPLOY:-0}"

echo -e "\n${BOLD}╔══════════════════════════════════════════════════════════╗"
echo -e   "║   Data Engineer Code Challenge — ETL Pipeline Runner     ║"
echo -e   "╚══════════════════════════════════════════════════════════╝${RESET}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Prerrequisitos
# ─────────────────────────────────────────────────────────────────────────────
step "Verificando prerrequisitos"

command -v python3 >/dev/null 2>&1 || die "python3 no encontrado"
command -v aws     >/dev/null 2>&1 || die "AWS CLI no encontrado"
command -v sam     >/dev/null 2>&1 || die "SAM CLI no encontrado"

ok "python3  $(python3 --version | awk '{print $2}')"
ok "AWS CLI  $(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)"
ok "SAM CLI  $(sam --version | awk '{print $NF}')"

# Verifica que el CSV de datos esté presente
if [[ ! -f "data/battery14_df.csv" ]]; then
    die "data/battery14_df.csv no encontrado. ¿Clonaste el repositorio completo?"
fi
ok "data/battery14_df.csv encontrado"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Dependencias Python
# ─────────────────────────────────────────────────────────────────────────────
step "Instalando dependencias Python"

# La imagen base (python:3.11-slim-bullseye) no tiene restricciones de
# "externally-managed-environment", así que pip funciona directo.
pip install -q --no-cache-dir -r requirements.txt

ok "Dependencias instaladas"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Tests unitarios
# ─────────────────────────────────────────────────────────────────────────────
step "Ejecutando tests unitarios (pytest + moto)"

python3 -m pytest tests/ -v --tb=short \
    --cov=lambda/start_state_machine \
    --cov-report=term-missing \
    || die "Tests fallidos. Corrige los errores antes de hacer deploy."

ok "Todos los tests pasaron"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 & 6 — SAM build + deploy
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_DEPLOY" == "1" ]]; then
    warn "SKIP_DEPLOY=1 — omitiendo sam build y sam deploy"
else
    step "Construyendo aplicación SAM (sam build)"

    # --no-use-container: ya corremos dentro de Python 3.11 (igual que el
    # runtime de la Lambda), no necesitamos lanzar otro contenedor Docker.
    sam build \
        --no-use-container \
        --profile "$AWS_PROFILE"

    ok "SAM build completado"

    step "Desplegando stack CloudFormation: ${STACK_NAME}"

    DEPLOY_ARGS=(
        sam deploy
        --stack-name    "$STACK_NAME"
        --region        "$REGION"
        --profile       "$AWS_PROFILE"
        --resolve-s3
        --capabilities  CAPABILITY_IAM CAPABILITY_NAMED_IAM
        --no-confirm-changeset
        --no-fail-on-empty-changeset
    )

    if [[ -n "$ALERT_EMAIL" ]]; then
        DEPLOY_ARGS+=(--parameter-overrides "AlertEmail=${ALERT_EMAIL}")
        ok "Alert email: ${ALERT_EMAIL}"
    else
        warn "ALERT_EMAIL no definido — se usará el email en samconfig.toml"
        warn "Para cambiarlo: ALERT_EMAIL=tu@email.com docker compose up"
    fi

    "${DEPLOY_ARGS[@]}"
    ok "Stack desplegado exitosamente"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Upload de datos y scripts Glue a S3
# ─────────────────────────────────────────────────────────────────────────────
step "Subiendo datos y scripts Glue a S3"

python3 scripts/upload_data.py

ok "Upload completado"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Trigger del pipeline via Lambda
# ─────────────────────────────────────────────────────────────────────────────
step "Invocando Lambda para iniciar el ETL"

LAMBDA_NAME="cc-de-start-state-machine"
PAYLOAD='{"executionDate":"'"$(date -u +%Y-%m-%d)"'"}'

RESPONSE=$(aws lambda invoke \
    --function-name        "$LAMBDA_NAME" \
    --payload              "$PAYLOAD" \
    --cli-binary-format    raw-in-base64-out \
    --profile              "$AWS_PROFILE" \
    --region               "$REGION" \
    /tmp/lambda_response.json \
    --query                'StatusCode' \
    --output               text 2>&1)

if [[ "$RESPONSE" == "200" ]]; then
    EXECUTION_ARN=$(python3 -c \
        "import json; d=json.load(open('/tmp/lambda_response.json')); print(d.get('executionArn','N/A'))")
    ok "Lambda invocada exitosamente"
    echo -e "    Execution ARN: ${CYAN}${EXECUTION_ARN}${RESET}"
else
    die "Lambda invocation failed (HTTP ${RESPONSE}). Revisa CloudWatch Logs."
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Verificación: URLs y queries Athena
# ─────────────────────────────────────────────────────────────────────────────
ACCOUNT_ID=$(aws sts get-caller-identity \
    --profile "$AWS_PROFILE" \
    --query   Account \
    --output  text)

SFN_URL="https://${REGION}.console.aws.amazon.com/states/home?region=${REGION}#/executions/details/${EXECUTION_ARN}"
ATHENA_URL="https://${REGION}.console.aws.amazon.com/athena/home?region=${REGION}#/query-editor"

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Pipeline en ejecución — cómo verificar los resultados   ${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${YELLOW}1. Monitorea la ejecución del Step Function (~3-5 min):${RESET}"
echo -e "   ${SFN_URL}"
echo ""
echo -e "${YELLOW}2. Cuando la ejecución esté SUCCEEDED, corre estas queries en Athena:${RESET}"
echo -e "   Abre: ${ATHENA_URL}"
echo ""
echo -e "   -- Total de registros (esperado: 294)"
echo -e "   ${CYAN}SELECT COUNT(*) AS total FROM cc_data_engineer_db.battery_filtered;${RESET}"
echo ""
echo -e "   -- Confirmar tipo de tabla Iceberg"
echo -e "   ${CYAN}SHOW TBLPROPERTIES cc_data_engineer_db.battery_filtered;${RESET}"
echo ""
echo -e "   -- Spot-check de datos"
echo -e "   ${CYAN}SELECT gender, country, MIN(age) AS min_age, MIN(raw_score) AS min_score"
echo -e "   FROM cc_data_engineer_db.battery_filtered"
echo -e "   GROUP BY gender, country;${RESET}"
echo ""
echo -e "${YELLOW}3. Bucket S3 para output de Athena (configúralo en Athena Settings):${RESET}"
echo -e "   s3://cc-data-engineer-${ACCOUNT_ID}-${REGION}/athena/"
echo ""
echo -e "${GREEN}${BOLD}  ¡Listo! El pipeline completo está corriendo.${RESET}"
echo ""
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           