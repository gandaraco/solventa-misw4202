#!/usr/bin/env bash
export LOG_LEVEL=WARNING

corrida () {          # $1=usuarios  $2=etiqueta
  docker compose restart validator >/dev/null 2>&1
  sleep 6
  ( for i in $(seq 1 13); do
      docker compose exec -T rabbitmq rabbitmqctl list_queues --quiet name messages 2>/dev/null | sed 's/^/  /'
      sleep 5
    done ) > /tmp/s.txt 2>/dev/null &
  local S=$!
  USERS=$1 SPAWN=$1 DURATION=60s RUN="$(echo $2 | tr ' ' '_')" \
    docker compose --profile carga run --rm locust 2>&1 | grep Aggregated | head -1
  wait $S 2>/dev/null || true
  sleep 4
  python medir.py "$2"
  grep -E '^\s+q\.' /tmp/s.txt | awk '{if($2>m[$1])m[$1]=$2} END{for(q in m) printf "  %-24s pico %6d\n", q, m[q]}' | sort
}

echo "==================== FASE 1: buscar la rodilla ===================="
for U in 40 50 60; do
  echo "############ $U usuarios ############"
  corrida $U "$U usuarios"
done

echo ""
echo "==================== FASE 2: condicion A (control, sin fallo) ===================="
RATING3_MODE=normal docker compose up -d --force-recreate rating3 >/dev/null 2>&1
sleep 6
docker compose logs --no-color --tail=5 rating3 | grep arranque | sed 's/.*evento=/  /'
corrida 30 "A control - rating3 normal - 30 usuarios"

echo ""
echo "==================== FASE 3: condicion D (replica caida) ===================="
docker compose up -d --force-recreate rating3 >/dev/null 2>&1
sleep 5
docker compose stop rating3 >/dev/null 2>&1
sleep 3
corrida 30 "D degradada - rating3 detenida - 30 usuarios"

echo ""
echo "==================== restaurando ===================="
docker compose start rating3 >/dev/null 2>&1
sleep 4
docker compose exec -T rabbitmq rabbitmqctl purge_queue q.rating3.comando 2>/dev/null | tail -1
docker compose logs --no-color --tail=5 rating3 | grep arranque | sed 's/.*evento=/  /'
