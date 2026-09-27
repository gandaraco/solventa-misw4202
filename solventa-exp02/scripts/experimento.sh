#!/usr/bin/env bash
# Corrida completa de EXP-02 sobre el compose general, desde cero y con evidencia.
#
#   bash scripts/experimento.sh            # desde solventa-exp02/ (Git Bash, Linux o macOS)
#
# 1. Baja el stack y borra sus volumenes (cada corrida parte de un estado limpio).
# 2. Genera la CA y el material si no existe; construye y levanta el stack.
# 3. Arranca las capturas (tcpdump en gateway, ms-pagos y kafka).
# 4. Verificaciones: infraestructura (Donaldo), confidencialidad (Oscar) e
#    integridad (Hernan), todas contra el stack integrado.
# 5. Detiene las capturas y las analiza; revisa los logs de todos los contenedores.
# 6. Consolida en evidencias/<RUN_ID>/infraestructura/resumen.json.
# El stack queda arriba para inspeccion: `docker compose down -v` para bajarlo.
set -uo pipefail
cd "$(dirname "$0")/.."

export RUN_ID="${RUN_ID:-exp02_$(date -u +%Y%m%dT%H%M%SZ)_infra}"
DC="docker compose -f docker-compose.yml"
FALLAS=0

paso() { printf '\n>>> %s\n' "$*"; }
correr() { "$@" || FALLAS=$((FALLAS + 1)); }

paso "Corrida $RUN_ID"
$DC --profile captura down -v --remove-orphans >/dev/null 2>&1

if [ ! -f certs/ca.crt ] || [ ! -f certs/kafka.p12 ] || [ ! -f secretos/autorizador_jwt.key ]; then
  paso "Generando CA, certificados y llaves de desarrollo"
  $DC run --rm material || exit 1
fi

paso "Construyendo y levantando el stack"
$DC --profile captura --profile herramientas build || exit 1
$DC up -d || exit 1

paso "Arrancando capturas"
mkdir -p "evidencias/$RUN_ID/capturas"
$DC --profile captura up -d captura-gateway captura-pagos captura-kafka || exit 1

paso "Verificacion de infraestructura e integracion"
correr $DC run --rm verificacion-infraestructura
paso "Verificacion del tramo de confidencialidad (stack integrado)"
correr $DC run --rm verificacion
paso "Verificacion del tramo de integridad (stack integrado)"
correr $DC run --rm verificacion-integridad

paso "Deteniendo capturas y analizandolas"
$DC --profile captura stop captura-gateway captura-pagos captura-kafka
correr $DC run --rm verificacion-infraestructura python scripts/verificar_infraestructura.py --capturas

paso "Revisando logs de todos los contenedores"
$DC logs --no-color > "evidencias/$RUN_ID/logs_contenedores.txt"
correr $DC run --rm -T verificacion-infraestructura python scripts/verificar_infraestructura.py --logs \
  < "evidencias/$RUN_ID/logs_contenedores.txt"

paso "Resumen"
correr $DC run --rm verificacion-infraestructura python scripts/verificar_infraestructura.py --resumen

if [ "$FALLAS" -eq 0 ]; then
  paso "OK: todas las verificaciones pasaron. Evidencia en evidencias/$RUN_ID/"
else
  paso "FALLAS: $FALLAS paso(s) con verificaciones fallidas. Evidencia en evidencias/$RUN_ID/"
fi
exit "$FALLAS"
