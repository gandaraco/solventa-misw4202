# scripts/crear_topicos.py
"""Crea los topicos de EXP-02 en Kafka, por mTLS, y espera a que el broker responda.

Corre como servicio de un solo uso (kafka-topicos) antes que productores y
consumidores; es idempotente.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from confluent_kafka.admin import AdminClient, NewTopic  # noqa: E402

from comun import kafka  # noqa: E402

TOPICOS = [t for t in os.getenv("TOPICOS", "solventa.consentimiento.eventos").split(",") if t]


def main(espera_max_s=120):
    admin = AdminClient(kafka.config_desde_entorno())
    limite = time.monotonic() + espera_max_s
    while True:
        try:
            existentes = set(admin.list_topics(timeout=5).topics)
            break
        except Exception as exc:  # noqa: BLE001 - el broker aun arranca
            if time.monotonic() > limite:
                print("evento=kafka_no_disponible causa=%s" % exc)
                return 1
            time.sleep(2)
    nuevos = [NewTopic(t, num_partitions=1, replication_factor=1)
              for t in TOPICOS if t not in existentes]
    for topico, futuro in admin.create_topics(nuevos).items() if nuevos else ():
        futuro.result()
        print("evento=topico_creado topico=%s" % topico)
    print("evento=topicos_listos topicos=%s" % ",".join(TOPICOS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
