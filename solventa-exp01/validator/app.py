# validator/app.py
import json
import logging
import os
import sys
import threading
import time
from collections import OrderedDict

import pika
from prometheus_client import Counter, Histogram, start_http_server

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(os.getenv("SERVICE_ID", "validator"))

# La etiqueta cierre separa el costo real de la tactica (quorum) del parametro
# de diseno (timeout). Solo el primero generaliza a ASR-D3.
# Los buckets estan pegados al presupuesto de 100 ms: el corte en 0.1 permite
# reportar la proporcion dentro de presupuesto sin interpolar.
LATENCIA = Histogram(
    "asr_d1_latencia_deteccion_segundos",
    "Tiempo entre publicacion del comando y veredicto del Validador",
    ["cierre"],
    buckets=[0.001, 0.0025, 0.005, 0.0075, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15,
             0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)
VEREDICTOS = Counter(
    "asr_d1_veredictos_total", "Veredictos emitidos", ["cierre", "veredicto"]
)
DIVERGENCIAS = Counter(
    "asr_d1_divergencias_total", "Respuestas que no coincidieron con la mayoria", ["instancia"]
)
TARDIAS = Counter(
    "asr_d1_respuestas_tardias_total", "Respuestas llegadas tras el veredicto", ["instancia"]
)

TIMEOUT_S = float(os.getenv("TIMEOUT_S", "0.08"))  # punto de partida a calibrar
REPLICAS = int(os.getenv("REPLICAS", "3"))
DECIDIDOS_MAX = 20000  # cota de memoria para el registro de veredictos ya emitidos

RESOLUCION_S = float(os.getenv("RESOLUCION_S", "0.005"))  # granularidad del barrido

# Un unico hilo barredor vence los pendientes, en vez de un threading.Timer por
# peticion: a 175 req/s eso significaba crear y cancelar 175 hilos del sistema
# operativo por segundo, y era el cuello de botella del Validador.
# Como TIMEOUT_S es constante, el orden de insercion es el orden de expiracion:
# basta con mirar el frente del OrderedDict.
pendientes = OrderedDict()  # correlation_id -> {"respuestas", "ts_publicado", "expira"}
decididos = OrderedDict()   # correlation_id -> True, en orden de insercion
lock = threading.Lock()


def _marcar_decidido(cid):
    """Registra el cid como cerrado para descartar respuestas tardias, con memoria acotada."""
    decididos[cid] = True
    while len(decididos) > DECIDIDOS_MAX:
        decididos.popitem(last=False)


def decidir(correlation_id, cierre):
    with lock:
        entrada = pendientes.pop(correlation_id, None)
        if entrada is None:
            return  # ya lo cerro el otro camino (quorum o timeout)
        _marcar_decidido(correlation_id)

    respuestas = entrada["respuestas"]
    n = len(respuestas)
    valores = [r["resultado"] for r in respuestas]
    mayoria = max(set(valores), key=valores.count) if valores else None
    votos = valores.count(mayoria) if mayoria is not None else 0
    divergentes = [r.get("instancia", "?") for r in respuestas if r["resultado"] != mayoria]
    veredicto = "valida" if votos >= 2 else "inconsistente_o_insuficiente"

    ts_pub = entrada["ts_publicado"]
    VEREDICTOS.labels(cierre=cierre, veredicto=veredicto).inc()
    for inst in divergentes:
        DIVERGENCIAS.labels(instancia=inst).inc()

    if ts_pub:
        latencia = time.time() - ts_pub
        LATENCIA.labels(cierre=cierre).observe(latencia)
        lat_txt = "%.1f" % (latencia * 1000)
    else:
        # Sin sello del Gateway no se puede medir: se registra pero NO se observa,
        # para no contaminar el histograma con un valor que no significa nada.
        lat_txt = "NA"

    log.info(
        "evento=veredicto corr=%s cierre=%s n=%d/%d veredicto=%s mayoria=%s votos=%d divergentes=%s latencia_ms=%s",
        correlation_id, cierre, n, REPLICAS, veredicto, mayoria, votos,
        ",".join(divergentes) or "-", lat_txt,
    )


def barrer():
    """Cierra por timeout los pendientes vencidos. Un solo hilo para todo el proceso."""
    while True:
        ahora = time.monotonic()
        vencidos = []
        with lock:
            for cid, entrada in pendientes.items():
                if entrada["expira"] > ahora:
                    break  # orden de insercion == orden de expiracion
                vencidos.append(cid)
        for cid in vencidos:
            decidir(cid, "timeout")
        time.sleep(RESOLUCION_S)


def callback(ch, method, properties, body):
    data = json.loads(body)
    cid = properties.correlation_id

    with lock:
        if cid in decididos:
            accion, n_actual = "tardia", 0
        else:
            if cid not in pendientes:
                pendientes[cid] = {
                    "respuestas": [],
                    "ts_publicado": data.get("ts_publicado"),
                    "expira": time.monotonic() + TIMEOUT_S,
                }
            pendientes[cid]["respuestas"].append(data)
            n_actual = len(pendientes[cid]["respuestas"])
            accion = "quorum" if n_actual >= REPLICAS else "parcial"

    ch.basic_ack(delivery_tag=method.delivery_tag)

    if accion == "tardia":
        TARDIAS.labels(instancia=str(data.get("instancia"))).inc()
        log.warning(
            "evento=tardia corr=%s instancia=%s descartada=si (veredicto ya emitido)",
            cid, data.get("instancia"),
        )
        return

    log.info(
        "evento=respuesta corr=%s instancia=%s resultado=%s n=%d/%d",
        cid, data.get("instancia"), data.get("resultado"), n_actual, REPLICAS,
    )

    if accion == "quorum":
        decidir(cid, "quorum")


def conectar_rabbitmq(host="rabbitmq", intentos=10, espera=3):
    for i in range(intentos):
        try:
            return pika.BlockingConnection(pika.ConnectionParameters(host=host))
        except pika.exceptions.AMQPConnectionError:
            log.warning("evento=reintento_conexion intento=%d/%d", i + 1, intentos)
            time.sleep(espera)
    raise RuntimeError("No se pudo conectar a RabbitMQ tras varios intentos")


start_http_server(8000)  # expone /metrics para Prometheus
threading.Thread(target=barrer, daemon=True, name="barredor").start()
conn = conectar_rabbitmq()
ch = conn.channel()
ch.exchange_declare(exchange="solventa.cotizacion", exchange_type="topic", durable=True)
ch.queue_declare(queue="q.cotizacion.respuesta", durable=True)
ch.queue_bind(exchange="solventa.cotizacion", queue="q.cotizacion.respuesta", routing_key="cotizacion.respuesta")
ch.basic_qos(prefetch_count=int(os.getenv("PREFETCH", "100")))
ch.basic_consume(queue="q.cotizacion.respuesta", on_message_callback=callback)
log.info("evento=arranque servicio=validator replicas=%d timeout_ms=%.0f", REPLICAS, TIMEOUT_S * 1000)
ch.start_consuming()
