"""Consumidor de eventos firmados de Consentimiento.

La verificacion ocurre antes de llamar ``almacen.activar``. Este orden es la
propiedad que demuestran INTEG-02 a INTEG-05.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

from comun import jws, registro
from comun.auditoria import AuditoriaLog, ClienteAuditoria
from suscripcion.almacen import AlmacenSuscripcion

log = registro.configurar("ms-suscripcion")


def _llaves_desde_entorno():
    ruta = os.getenv("JWS_PUBLICA_ARCHIVO")
    kid = os.getenv("JWS_KID", "consentimiento-v1")
    if not ruta:
        raise RuntimeError("JWS_PUBLICA_ARCHIVO_requerido")
    return {kid: Path(ruta).read_bytes()}


def _auditoria_desde_entorno():
    url = os.getenv("AUDITORIA_URL")
    return ClienteAuditoria(url) if url else AuditoriaLog(log)


def crear_app(almacen=None, llaves_publicas=None, auditoria=None):
    almacen = almacen or AlmacenSuscripcion(os.getenv("BD_URL", "sqlite:///suscripcion.db"))
    llaves_publicas = llaves_publicas or _llaves_desde_entorno()
    auditoria = auditoria or _auditoria_desde_entorno()
    app = Flask(__name__)

    @app.post("/eventos")
    def consumir_evento():
        sobre = request.get_json(silent=True) or {}
        event_id = _texto(sobre.get("eventId"), "evento_desconocido")
        marcador = _texto(sobre.get("marcador"), None)
        try:
            payload = jws.verificar(sobre.get("jws"), llaves_publicas)
            _validar_payload(payload, event_id)
        except jws.JWSInvalido as exc:
            _auditar(auditoria, event_id, marcador, "RECHAZADO", exc.motivo)
            log.warning("evento=jws_rechazado eventId=%s motivo=%s", event_id, exc.motivo)
            return jsonify({"estado": "rechazado", "motivo": exc.motivo,
                            "eventId": event_id}), 422

        datos = payload["datos"]
        estado = almacen.activar(datos["suscripcionId"], event_id,
                                 datetime.now(timezone.utc))
        _auditar(auditoria, event_id, marcador, "ACEPTADO", None,
                 entidad_id=datos["suscripcionId"])
        log.info("evento=jws_aceptado eventId=%s suscripcion=%s",
                 event_id, datos["suscripcionId"])
        return jsonify({"estado": "procesado", "eventId": event_id,
                        "suscripcion": estado}), 202

    @app.get("/suscripciones/<suscripcion_id>")
    def consultar(suscripcion_id):
        return jsonify(almacen.estado(suscripcion_id))

    @app.get("/salud")
    def salud():
        return jsonify({"ok": True})

    return app


def _validar_payload(payload, event_id):
    if payload.get("eventId") != event_id:
        raise jws.JWSInvalido("event_id_no_coincide")
    if payload.get("tipo") != "CONSENTIMIENTO_OTORGADO":
        raise jws.JWSInvalido("tipo_no_permitido")
    datos = payload.get("datos")
    if not isinstance(datos, dict) or not isinstance(datos.get("suscripcionId"), str):
        raise jws.JWSInvalido("payload_invalido")


def _auditar(cliente, event_id, marcador, resultado, motivo, entidad_id=None):
    cliente.registrar({
        "eventId": event_id, "marcador": marcador,
        "accion": "CONSENTIMIENTO_PROCESADO" if resultado == "ACEPTADO" else "JWS_RECHAZADO",
        "entidadAfectada": "Suscripcion",
        "entidadId": entidad_id or "sin_cambio",
        "actorId": "ms-suscripcion", "resultado": resultado, "motivo": motivo,
    })


def _texto(valor, defecto):
    return str(valor)[:64] if valor is not None else defecto
