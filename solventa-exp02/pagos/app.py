# pagos/app.py
"""MS Pagos (ASR-07): registra pagos de primas e indemnizaciones.

El PAN entra en la peticion, se envia al Servicio de Tokenizacion y se descarta.
Lo unico que se persiste, se registra en log o se devuelve es el token.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Flask, jsonify, request

from comun import registro, tls
from comun.ids import nuevo_id
from pagos.almacen import Almacen
from pagos.tokenizador import ClienteTokenizador, PanInvalido, TokenizadorNoDisponible

log = registro.configurar("ms-pagos")

CONCEPTOS = ("prima", "indemnizacion")


def _validar(datos):
    """Valida todo menos el PAN, que valida el tokenizador. Devuelve (campos, error)."""
    try:
        monto = Decimal(str(datos.get("monto")))
    except InvalidOperation:
        return None, "monto_invalido"
    if not monto.is_finite() or monto <= 0:
        return None, "monto_invalido"
    concepto = datos.get("concepto")
    if concepto not in CONCEPTOS:
        return None, "concepto_invalido"
    moneda = datos.get("moneda", "COP")
    if not (isinstance(moneda, str) and len(moneda) == 3 and moneda.isalpha()):
        return None, "moneda_invalida"
    if not isinstance(datos.get("pan"), str):
        return None, "pan_invalido"
    return {
        "monto": monto.quantize(Decimal("0.01")),
        "moneda": moneda.upper(),
        "concepto": concepto,
        "poliza_id": _texto_opcional(datos.get("polizaId"), 40),
        "referencia": _texto_opcional(datos.get("referencia"), 64),
    }, None


def _texto_opcional(valor, largo):
    return str(valor)[:largo] if valor is not None else None


def _utc(fecha):
    # SQLite (pruebas) devuelve la fecha sin zona; Postgres la conserva.
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _a_json(fila):
    return {
        "pagoId": fila["pago_id"],
        "tokenTarjeta": fila["token_tarjeta"],
        "ultimos4": fila["ultimos4"],
        "monto": str(fila["monto"]),
        "moneda": fila["moneda"],
        "concepto": fila["concepto"],
        "polizaId": fila["poliza_id"],
        "referencia": fila["referencia"],
        "estado": fila["estado"],
        "fechaPago": _utc(fila["fecha_pago"]).isoformat(),
    }


def _cliente_desde_entorno():
    cfg_tls = tls.config_desde_entorno()
    cert, clave, ca = cfg_tls if cfg_tls else (None, None, None)
    return ClienteTokenizador(
        os.getenv("TOKENIZADOR_URL", "http://localhost:5102"),
        cert=cert, clave=clave, ca=ca,
        timeout_s=float(os.getenv("TOKENIZADOR_TIMEOUT_S", "2")),
    )


def crear_app(almacen=None, tokenizador=None):
    almacen = almacen or Almacen(os.getenv("BD_URL", "sqlite:///pagos.db"))
    tokenizador = tokenizador or _cliente_desde_entorno()
    app = Flask(__name__)

    @app.post("/pagos")
    def registrar_pago():
        datos = request.get_json(silent=True) or {}
        campos, error = _validar(datos)
        if error:
            # Se valida antes de tokenizar: una peticion invalida no debe hacer
            # viajar el PAN a ningun lado.
            log.info("evento=pago_rechazado motivo=%s", error)
            return jsonify({"error": error}), 400

        try:
            token, ultimos4 = tokenizador.tokenizar(datos["pan"])
        except PanInvalido:
            log.info("evento=pago_rechazado motivo=pan_invalido")
            return jsonify({"error": "pan_invalido"}), 400
        except TokenizadorNoDisponible as exc:
            # Sin token no hay pago: persistir el PAN "mientras tanto" es justo
            # lo que ASR-07 prohibe.
            log.error("evento=tokenizador_no_disponible causa=%s", exc)
            return jsonify({"error": "tokenizador_no_disponible"}), 503
        finally:
            datos.pop("pan", None)

        fila = dict(
            campos,
            pago_id=nuevo_id("pag"),
            token_tarjeta=token,
            ultimos4=ultimos4,
            estado="registrado",
            fecha_pago=datetime.now(timezone.utc),
        )
        almacen.guardar(fila)
        log.info(
            "evento=pago_registrado pago=%s token=%s concepto=%s monto=%s moneda=%s",
            fila["pago_id"], token, fila["concepto"], fila["monto"], fila["moneda"],
        )
        # Contrato con Auditoria (Hernan) pendiente: por ahora se deja el
        # registro con los campos de RegistroAuditoria (VC-004) en el log.
        log.info("evento=auditoria accion=PAGO_REGISTRADO entidad=Pago entidadId=%s actorId=ms-pagos",
                 fila["pago_id"])
        return jsonify(_a_json(fila)), 201

    @app.get("/pagos/<pago_id>")
    def consultar_pago(pago_id):
        fila = almacen.obtener(pago_id)
        if fila is None:
            return jsonify({"error": "no_encontrado"}), 404
        return jsonify(_a_json(fila))

    @app.get("/pagos")
    def buscar_por_referencia():
        referencia = request.args.get("referencia")
        if not referencia:
            return jsonify({"error": "referencia_requerida"}), 400
        return jsonify([_a_json(f) for f in almacen.por_referencia(referencia)])

    @app.get("/salud")
    def salud():
        return jsonify({"ok": True})

    if tls.config_desde_entorno() is None:
        log.warning("evento=tls_deshabilitado aviso=solo_para_desarrollo")
    log.info("evento=arranque servicio=ms-pagos")
    return app
