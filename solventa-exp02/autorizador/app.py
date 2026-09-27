# autorizador/app.py
"""Autorizador OAuth2 de EXP-02: client credentials con autenticacion mTLS (RFC 8705).

El cliente no manda secreto: se identifica con el certificado que ya valido el
handshake (CN = client_id). El JWT emitido queda ligado a ese certificado
(``cnf.x5t#S256``), de modo que el API Gateway lo rechaza si otro cliente lo
presenta. La CA dice QUIEN es cada parte; el Autorizador, QUE puede hacer (VC-001).
"""

import json
import os
from pathlib import Path

from flask import Flask, jsonify, request

from comun import jwt, registro, tls

log = registro.configurar("autorizador")

EMISOR = "solventa-autorizador"
AUDIENCIA = "solventa-api-gateway"

# client_id (CN del certificado) -> scopes que puede pedir. Minimo privilegio:
# un cliente que no esta aqui no obtiene token aunque su certificado sea valido.
CLIENTES_POR_DEFECTO = {
    "harness": ["pagos:escribir", "pagos:leer", "consentimientos:escribir",
                "suscripciones:leer"],
}


def _clientes_desde_entorno():
    valor = os.getenv("AUTORIZADOR_CLIENTES")
    return json.loads(valor) if valor else CLIENTES_POR_DEFECTO


def _llave_desde_entorno():
    ruta = os.getenv("JWT_PRIVADA_ARCHIVO")
    if not ruta:
        raise SystemExit("Falta JWT_PRIVADA_ARCHIVO")
    return Path(ruta).read_bytes()


def _error(codigo, error, http):
    log.info("evento=token_rechazado motivo=%s", codigo)
    return jsonify({"error": error, "error_description": codigo}), http


def crear_app(llave_privada=None, clientes=None, extraer_certificado=tls.certificado_cliente):
    llave_privada = llave_privada or _llave_desde_entorno()
    clientes = clientes if clientes is not None else _clientes_desde_entorno()
    kid = os.getenv("JWT_KID", "autorizador-v1")
    duracion_s = int(os.getenv("JWT_DURACION_S", "300"))
    app = Flask(__name__)

    @app.post("/oauth/token")
    def emitir_token():
        certificado = extraer_certificado(request.environ)
        if certificado is None:
            return _error("sin_certificado", "invalid_client", 401)
        sujeto, huella = certificado
        permitidos = clientes.get(sujeto)
        if permitidos is None:
            return _error("cliente_no_registrado", "invalid_client", 401)
        datos = request.form if request.form else (request.get_json(silent=True) or {})
        if datos.get("grant_type") != "client_credentials":
            return _error("grant_no_soportado", "unsupported_grant_type", 400)
        pedidos = set(str(datos.get("scope") or "").split()) or set(permitidos)
        if not pedidos <= set(permitidos):
            return _error("scope_no_permitido", "invalid_scope", 400)

        token = jwt.emitir(sujeto, pedidos, huella, llave_privada, kid,
                           EMISOR, AUDIENCIA, duracion_s)
        log.info("evento=token_emitido sujeto=%s scope=%s", sujeto, ",".join(sorted(pedidos)))
        return jsonify({"access_token": token, "token_type": "Bearer",
                        "expires_in": duracion_s, "scope": " ".join(sorted(pedidos))})

    @app.get("/salud")
    def salud():
        return jsonify({"ok": True})

    log.info("evento=arranque servicio=autorizador clientes=%s", ",".join(sorted(clientes)))
    return app
