#!/usr/bin/env bash
# Rampa de carga con muestreo de colas: encuentra el punto de saturacion.
set -e
for U in "$@"; do
  echo ""
  echo "############ ESCALON: $U usuarios ############"
  docker compose restart validator >/dev/null 2>&1
  sleep 4
  # muestrea la profundidad de las colas durante la corrida
  ( for i in $(seq 1 12); do
      docker compose exec -T rabbitmq rabbitmqctl list_queues --quiet name messages 2>/dev/null \
        | awk -v u="$U" '{printf "  cola %-24s %s\n", $1, $2}' | tr '\n' '|'
      echo ""
      sleep 5
    done ) > "/tmp/colas_$U.txt" 2>/dev/null &
  MUESTREO=$!
  USERS=$U SPAWN=$U DURATION=60s RUN="rampa_$U" \
    docker compose --profile carga run --rm locust 2>&1 | grep -E '^ *POST|Aggregated' | head -2
  wait $MUESTREO 2>/dev/null || true
  sleep 3
  python medir.py "rampa - $U usuarios"
  echo "--- pico de mensajes encolados durante la corrida ---"
  tr '|' '\n' < "/tmp/colas_$U.txt" | grep -oE 'q\.[a-z.]+ +[0-9]+' | awk '{if($2>m[$1])m[$1]=$2} END{for(q in m) printf "  %-24s pico %s\n", q, m[q]}'
done
