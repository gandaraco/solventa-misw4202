# gateway/app.py
import json
import logging
import os
import sys
import threading
import time
import uuid

import pika
from flask import Flask, jsonify, request
from waitress import serve

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(os.getenv("SERVICE_ID", "gateway"))
logging.getLogger("waitress").setLevel(logging.WARNING)

app = Flask(__name__)

EXCHANGE = "solventa.cotizacion"
ROUTING_KEY = "cotizacion.comando"

# pika no es thread-safe: cada hilo del pool WSGI mantiene su propio canal y lo
# reutiliza entre peticiones. Abrir una conexion por peticion costaba ~11 ms,
# el 11% del presupuesto de 100 ms de ASR-D1.
_local = threading.local()


def _cerrar_canal():
    conn = getattr(_local, "conn", None)
    try:
        if conn is not None and conn.is_open:
            conn.close()
    except Exception:
        pass
    _local.conn = None
    _local.ch = None


def _canal(reconectar=False):
    if reconectar:
        _cerrar_canal()
    ch = getattr(_local, "ch", None)
    if ch is not None and ch.is_open:
        return ch
    # heartbeat=0: BlockingConnection solo atiende heartbeats dentro de una llamada
    # bloqueante, asi que un canal de publicacion ocioso los pierde y el broker lo
    # cierra a los 60 s. La reconexion costaba ~16 ms dentro del presupuesto de
    # ASR-D1. Estamos en un unico host Docker, y el reintento de publish_comando
    # sigue cubriendo las caidas reales.
    conn = pika.BlockingConnection(
        pika.ConnectionParameters(host="rabbitmq", heartbeat=0, blocked_connection_timeout=30)
    )
    ch = conn.channel()
    ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    _local.conn = conn
    _local.ch = ch
    log.info("evento=canal_abierto hilo=%s", threading.current_thread().name)
    return ch


def publish_comando(payload):
    correlation_id = str(uuid.uuid4())
    props = pika.BasicProperties(correlation_id=correlation_id, delivery_mode=2)
    for intento in (1, 2):
        try:
            ch = _canal(reconectar=(intento == 2))
            body = json.dumps({**payload, "ts_publicado": time.time()})
            ch.basic_publish(exchange=EXCHANGE, routing_key=ROUTING_KEY, body=body, properties=props)
            break
        except (pika.exceptions.AMQPError, OSError) as exc:
            if intento == 2:
                log.error("evento=fallo_publicacion corr=%s causa=%s", correlation_id, type(exc).__name__)
                raise
            log.warning("evento=reconectando corr=%s causa=%s", correlation_id, type(exc).__name__)
    log.info("evento=publicado corr=%s rk=%s", correlation_id, ROUTING_KEY)
    return correlation_id


@app.route("/cotizacion", methods=["POST"])
def solicitar_cotizacion():
    correlation_id = publish_comando(request.json)
    # No esperamos el veredicto - esto es "publicar y liberar la conexion"
    return jsonify({"correlationId": correlation_id, "status": "en_proceso"}), 202


@app.route("/salud", methods=["GET"])
def salud():
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    hilos = int(os.getenv("WSGI_THREADS", "16"))
    log.info("evento=arranque servicio=gateway puerto=5000 hilos=%d", hilos)
    serve(app, host="0.0.0.0", port=5000, threads=hilos)
