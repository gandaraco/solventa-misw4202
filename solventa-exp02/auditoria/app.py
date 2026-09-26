import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from auditoria.almacen import AlmacenAuditoria
from comun import registro
from comun.ids import nuevo_id

log = registro.configurar("auditoria")
RESULTADOS = {"ACEPTADO", "RECHAZADO"}


def crear_app(almacen=None):
    almacen = almacen or AlmacenAuditoria(os.getenv("BD_URL", "sqlite:///auditoria.db"))
    app = Flask(__name__)

    @app.post("/registros")
    def crear_registro():
        datos = request.get_json(silent=True) or {}
        requeridos = ("accion", "entidadAfectada", "entidadId", "actorId", "resultado")
        if any(not isinstance(datos.get(c), str) or not datos[c] for c in requeridos):
            return jsonify({"error": "registro_invalido"}), 400
        if datos["resultado"] not in RESULTADOS:
            return jsonify({"error": "resultado_invalido"}), 400
        fila = {
            "registro_id": nuevo_id("aud"),
            "event_id": _opcional(datos.get("eventId")),
            "marcador": _opcional(datos.get("marcador")),
            "accion": datos["accion"][:64],
            "entidad_afectada": datos["entidadAfectada"][:64],
            "entidad_id": datos["entidadId"][:64],
            "actor_id": datos["actorId"][:64],
            "resultado": datos["resultado"],
            "motivo": _opcional(datos.get("motivo")),
            "timestamp": datetime.now(timezone.utc),
            "detalles": datos.get("detalles") if isinstance(datos.get("detalles"), dict) else {},
        }
        creado = almacen.agregar(fila)
        log.info("evento=auditoria accion=%s entidad=%s entidadId=%s resultado=%s motivo=%s",
                 fila["accion"], fila["entidad_afectada"], fila["entidad_id"],
                 fila["resultado"], fila["motivo"] or "ninguno")
        return jsonify(creado), 201

    @app.get("/registros")
    def consultar():
        return jsonify(almacen.buscar(request.args.get("eventId"),
                                     request.args.get("marcador")))

    @app.get("/salud")
    def salud():
        return jsonify({"ok": True})

    return app


def _opcional(valor):
    return str(valor)[:64] if valor is not None else None
