# tokenizacion/app.py
"""Servicio de Tokenizacion (ASR-07).

Recibe un PAN y devuelve un token. No expone ninguna operacion de
destokenizacion: en el alcance de EXP-02 ningun otro componente necesita el
PAN de vuelta, y una operacion que no existe no se puede abusar.
"""

import os

from flask import Flask, jsonify, request

from comun import pan as pan_util
from comun import registro, tls
from tokenizacion.boveda import Boveda

log = registro.configurar("tokenizador")


def _secreto(nombre):
    """Lee un secreto de NOMBRE o del archivo en NOMBRE_ARCHIVO (secrets de Docker)."""
    ruta = os.getenv(nombre + "_ARCHIVO")
    if ruta:
        with open(ruta, "rb") as f:
            return f.read().strip()
    valor = os.getenv(nombre)
    if not valor:
        raise SystemExit("Falta el secreto %s (o %s_ARCHIVO)" % (nombre, nombre))
    return valor.encode()


def crear_app(boveda=None):
    if boveda is None:
        boveda = Boveda(
            os.getenv("BD_URL", "sqlite:///boveda.db"),
            _secreto("LLAVE_CIFRADO"),
            _secreto("LLAVE_HMAC"),
        )
    app = Flask(__name__)

    @app.post("/tokens")
    def tokenizar():
        datos = request.get_json(silent=True) or {}
        digitos = pan_util.normalizar(datos.get("pan"))
        if digitos is None:
            # Nunca se devuelve ni se registra el valor recibido: podria ser un
            # PAN real con un digito mal digitado.
            log.info("evento=pan_rechazado motivo=formato_o_luhn")
            return jsonify({"error": "pan_invalido"}), 400

        token, ultimos4, nuevo = boveda.tokenizar(digitos)
        del digitos, datos
        log.info("evento=tokenizado token=%s ultimos4=%s nuevo=%s", token, ultimos4, nuevo)
        return jsonify({"token": token, "ultimos4": ultimos4}), 201 if nuevo else 200

    @app.get("/salud")
    def salud():
        return jsonify({"ok": True})

    if tls.config_desde_entorno() is None:
        log.warning("evento=tls_deshabilitado aviso=solo_para_desarrollo")
    log.info("evento=arranque servicio=tokenizador")
    return app
