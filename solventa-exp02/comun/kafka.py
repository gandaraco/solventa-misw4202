# comun/kafka.py
"""Transporte de eventos sobre Kafka con TLS 1.3 y mTLS (VC-005: "Kafka con TLS").

El sobre que viaja es exactamente el del contrato JWS: {eventId, marcador, jws}.
Kafka solo lo transporta; la integridad la decide el consumidor al verificar la
firma, no el broker. El broker no tiene listener en claro: sin certificado de
la CA del experimento no hay conexion (ver kafka/server.properties).
"""

import json
import os
import threading
import time

from comun import tls


class PublicacionFallida(RuntimeError):
    pass


def config_desde_entorno():
    """Configuracion base de librdkafka; None si KAFKA_BOOTSTRAP no esta definido.

    Kafka sin TLS no es un modo valido: se aborta en lugar de degradar a texto claro.
    """
    bootstrap = os.getenv("KAFKA_BOOTSTRAP")
    if not bootstrap:
        return None
    cfg_tls = tls.config_desde_entorno()
    if cfg_tls is None:
        raise SystemExit("KAFKA_BOOTSTRAP requiere TLS_CERT, TLS_CLAVE y TLS_CA")
    cert, clave, ca = cfg_tls
    return {
        "bootstrap.servers": bootstrap,
        "security.protocol": "SSL",
        "ssl.certificate.location": cert,
        "ssl.key.location": clave,
        "ssl.ca.location": ca,
        "ssl.endpoint.identification.algorithm": "https",
        "client.id": os.getenv("SERVICE_ID", "solventa"),
    }


def _serializar(sobre):
    return json.dumps(sobre, sort_keys=True, separators=(",", ":")).encode("utf-8")


class PublicadorKafka:
    """Publica un sobre y espera la confirmacion del broker (acks=all)."""

    def __init__(self, config, topico, timeout_s=10, productor=None):
        if productor is None:
            from confluent_kafka import Producer
            productor = Producer(dict(config, **{"acks": "all", "enable.idempotence": True}))
        self._productor = productor
        self._topico = topico
        self._timeout_s = timeout_s

    def publicar(self, sobre):
        entrega = {}

        def confirmar(error, mensaje):
            entrega["error"], entrega["mensaje"] = error, mensaje

        clave = sobre.get("eventId")
        self._productor.produce(self._topico, value=_serializar(sobre),
                                key=clave.encode("utf-8") if clave else None,
                                on_delivery=confirmar)
        self._productor.flush(self._timeout_s)
        if "mensaje" not in entrega:
            raise PublicacionFallida("sin_confirmacion")
        if entrega["error"] is not None:
            raise PublicacionFallida(entrega["error"].name())
        mensaje = entrega["mensaje"]
        return {"topico": mensaje.topic(), "particion": mensaje.partition(),
                "offset": mensaje.offset()}


class ConsumidorKafka:
    """Entrega cada sobre al manejador y confirma el offset despues de procesarlo.

    Si el manejador falla (p. ej. Auditoria caida) el offset no se confirma y el
    mismo mensaje se reintenta: entrega al menos una vez. El procesador de
    MS Suscripcion es idempotente por eventId.
    """

    def __init__(self, config, topico, grupo, manejador, log, consumidor=None,
                 espera_reintento_s=1.0):
        if consumidor is None:
            from confluent_kafka import Consumer
            consumidor = Consumer(dict(config, **{
                "group.id": grupo,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }))
        self._consumidor = consumidor
        self._topico = topico
        self._manejador = manejador
        self._log = log
        self._espera_reintento_s = espera_reintento_s
        self._detener = threading.Event()
        self._hilo = None

    def iniciar(self):
        self._consumidor.subscribe([self._topico])
        self._hilo = threading.Thread(target=self._bucle, name="consumidor-kafka", daemon=True)
        self._hilo.start()
        self._log.info("evento=kafka_suscrito topico=%s", self._topico)
        return self

    def detener(self):
        self._detener.set()
        if self._hilo:
            self._hilo.join(timeout=5)
        self._consumidor.close()

    def _bucle(self):
        while not self._detener.is_set():
            self.procesar_uno()

    def procesar_uno(self, timeout_s=1.0):
        mensaje = self._consumidor.poll(timeout_s)
        if mensaje is None:
            return False
        if mensaje.error():
            self._log.warning("evento=kafka_error codigo=%s", mensaje.error().name())
            return False
        try:
            sobre = json.loads(mensaje.value())
        except (TypeError, ValueError):
            sobre = None
        if not isinstance(sobre, dict):
            # Un mensaje ilegible se trata como un sobre sin firma: el
            # procesador lo rechaza y lo deja en Auditoria.
            sobre = {}
        self._log.info("evento=kafka_consumido topico=%s particion=%s offset=%s",
                       mensaje.topic(), mensaje.partition(), mensaje.offset())
        try:
            self._manejador(sobre)
        except Exception as exc:  # noqa: BLE001 - se reintenta, no se pierde
            self._log.error("evento=kafka_procesamiento_fallido offset=%s causa=%s",
                            mensaje.offset(), type(exc).__name__)
            self._reintentar(mensaje)
            return False
        self._consumidor.commit(message=mensaje, asynchronous=False)
        return True

    def _reintentar(self, mensaje):
        from confluent_kafka import TopicPartition
        self._consumidor.seek(TopicPartition(mensaje.topic(), mensaje.partition(),
                                             mensaje.offset()))
        time.sleep(self._espera_reintento_s)
