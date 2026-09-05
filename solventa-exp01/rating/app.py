# rating/app.py
import json
import logging
import os
import sys
import time

import pika

MODE = os.environ.get("RATING_MODE", "normal")  # "normal" | "divergente"
QUEUE = os.environ["RATING_QUEUE"]  # q.rating1.comando, etc.
INSTANCIA = os.environ.get("SERVICE_ID", QUEUE)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(INSTANCIA)


def calcular_prima(payload):
    base = 100.0  # tu logica real de rating iria aqui
    if MODE == "divergente":
        return base * 3  # resultado deliberadamente incorrecto
    return base


def callback(ch, method, properties, body):
    data = json.loads(body)
    cid = properties.correlation_id
    log.info("evento=recibido corr=%s instancia=%s modo=%s", cid, INSTANCIA, MODE)

    # El cronometro arranca despues del log de entrada: escribir a stdout es una
    # operacion bloqueante que no forma parte del trabajo que queremos medir, y
    # haria que proceso_ms cambiara solo con mover LOG_LEVEL.
    t0 = time.perf_counter()
    resultado = calcular_prima(data)
    respuesta = json.dumps(
        {
            "resultado": resultado,
            # Se propaga el sello del Gateway: sin esto el Validador no puede medir
            # la latencia extremo a extremo y termina midiendo solo la ventana de join.
            "ts_publicado": data.get("ts_publicado"),
            "ts_respuesta": time.time(),
            "instancia": INSTANCIA,
        }
    )
    ch.basic_publish(
        exchange="solventa.cotizacion",
        routing_key="cotizacion.respuesta",
        body=respuesta,
        properties=pika.BasicProperties(correlation_id=cid),
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)
    log.info(
        "evento=respondido corr=%s instancia=%s resultado=%.2f proceso_ms=%.2f",
        cid, INSTANCIA, resultado, (time.perf_counter() - t0) * 1000,
    )


def conectar_rabbitmq(host="rabbitmq", intentos=10, espera=3):
    for i in range(intentos):
        try:
            return pika.BlockingConnection(pika.ConnectionParameters(host=host))
        except pika.exceptions.AMQPConnectionError:
            log.warning("evento=reintento_conexion intento=%d/%d", i + 1, intentos)
            time.sleep(espera)
    raise RuntimeError("No se pudo conectar a RabbitMQ tras varios intentos")


conn = conectar_rabbitmq()
ch = conn.channel()
ch.exchange_declare(exchange="solventa.cotizacion", exchange_type="topic", durable=True)
ch.queue_declare(queue=QUEUE, durable=True)
ch.queue_bind(exchange="solventa.cotizacion", queue=QUEUE, routing_key="cotizacion.comando")
ch.basic_qos(prefetch_count=int(os.getenv("PREFETCH", "50")))
ch.basic_consume(queue=QUEUE, on_message_callback=callback)
log.info("evento=arranque instancia=%s cola=%s modo=%s", INSTANCIA, QUEUE, MODE)
ch.start_consuming()
