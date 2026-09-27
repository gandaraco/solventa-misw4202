"""Productor de eventos de Consentimiento firmados con JWS.

Publica el sobre en Kafka si KAFKA_BOOTSTRAP esta definido; si no, por HTTP a
SUSCRIPCION_URL (adaptador determinista de docker-compose.integridad.yml).
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request

from comun import jws, kafka, registro
from comun.ids import nuevo_id

log = registro.configurar("ms-consentimiento")


class PublicadorHTTP:
    def __init__(self, url, timeout_s=2):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def publicar(self, sobre):
        respuesta = requests.post(self.url + "/eventos", json=sobre,
                                  timeout=self.timeout_s)
        respuesta.raise_for_status()
        return respuesta.json()


def _publicador_desde_entorno():
    cfg_kafka = kafka.config_desde_entorno()
    if cfg_kafka:
        return kafka.PublicadorKafka(
            cfg_kafka, os.getenv("TOPICO_CONSENTIMIENTOS", "solventa.consentimiento.eventos"))
    if os.getenv("SUSCRIPCION_URL"):
        return PublicadorHTTP(os.environ["SUSCRIPCION_URL"])
    return None


def _llave_desde_entorno():
    ruta = os.getenv("JWS_PRIVADA_ARCHIVO")
    if not ruta:
        raise RuntimeError("JWS_PRIVADA_ARCHIVO_requerido")
    return Path(ruta).read_bytes()


def crear_app(llave_privada=None, publicador=None):
    llave_privada = llave_privada or _llave_desde_entorno()
    if publicador is None:
        publicador = _publicador_desde_entorno()
    kid = os.getenv("JWS_KID", "consentimiento-v1")
    app = Flask(__name__)

    @app.post("/consentimientos")
    def otorgar():
        datos = request.get_json(silent=True) or {}
        suscripcion_id = datos.get("suscripcionId")
        actor_id = datos.get("actorId")
        if not isinstance(suscripcion_id, str) or not suscripcion_id:
            return jsonify({"error": "suscripcion_id_requerido"}), 400
        if not isinstance(actor_id, str) or not actor_id:
            return jsonify({"error": "actor_id_requerido"}), 400
        event_id = nuevo_id("evt")
        marcador = str(datos.get("marcador"))[:64] if datos.get("marcador") else None
        payload = {
            "eventId": event_id,
            "tipo": "CONSENTIMIENTO_OTORGADO",
            "emitidoEn": datetime.now(timezone.utc).isoformat(),
            "actorId": actor_id[:64],
            "datos": {"suscripcionId": suscripcion_id[:64]},
        }
        sobre = {"eventId": event_id, "marcador": marcador,
                 "jws": jws.firmar(payload, llave_privada, kid)}
        log.info("evento=jws_firmado eventId=%s tipo=CONSENTIMIENTO_OTORGADO", event_id)
        if publicador is None:
            return jsonify({**sobre, "publicado": False}), 201
        try:
            resultado = publicador.publicar(sobre)
        except (requests.RequestException, kafka.PublicacionFallida) as exc:
            log.error("evento=publicacion_fallida eventId=%s causa=%s",
                      event_id, type(exc).__name__)
            return jsonify({"error": "consumidor_no_disponible", "eventId": event_id}), 503
        return jsonify({**sobre, "publicado": True, "resultado": resultado}), 201

    @app.get("/salud")
    def salud():
        return jsonify({"ok": True})

    return app
