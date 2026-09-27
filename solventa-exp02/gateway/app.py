# gateway/app.py
"""API Gateway de EXP-02: unico punto de entrada del producto (VC-001, VC-005).

Antes de reenviar una peticion exige, en este orden:
1. mTLS: sin certificado de la CA del experimento no hay handshake (gunicorn).
2. Ruta conocida: lo que no esta en RUTAS no llega a ningun microservicio.
3. JWT del Autorizador, vigente, para esta audiencia y ligado al certificado
   que presenta el cliente (un token robado no sirve con otro certificado).
4. Scope de la ruta.
El reenvio al microservicio va tambien por mTLS, con el certificado del gateway.
Los rechazos se registran en Auditoria sin bloquear la respuesta (VC-003).
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request

from comun import auditoria as auditoria_util
from comun import jwt, registro, tls
from comun.pan import PATRON_PAN

log = registro.configurar("api-gateway")

EMISOR = "solventa-autorizador"
AUDIENCIA = "solventa-api-gateway"

_ID = r"[A-Za-z0-9_\-]{1,64}"

# (metodo, patron de la ruta, nombre para logs, destino, scope requerido)
RUTAS = (
    ("POST", re.compile(r"/pagos"), "POST /pagos", "ms-pagos", "pagos:escribir"),
    ("GET", re.compile(r"/pagos"), "GET /pagos", "ms-pagos", "pagos:leer"),
    ("GET", re.compile(r"/pagos/" + _ID), "GET /pagos/<id>", "ms-pagos", "pagos:leer"),
    ("POST", re.compile(r"/consentimientos"), "POST /consentimientos",
     "ms-consentimiento", "consentimientos:escribir"),
    ("GET", re.compile(r"/suscripciones/" + _ID), "GET /suscripciones/<id>",
     "ms-suscripcion", "suscripciones:leer"),
)

DESTINOS_POR_DEFECTO = {
    "ms-pagos": "https://ms-pagos:8443",
    "ms-consentimiento": "https://ms-consentimiento:8443",
    "ms-suscripcion": "https://ms-suscripcion:8443",
}


class DestinoNoDisponible(Exception):
    pass


class Reenviador:
    """Cliente mTLS hacia los microservicios."""

    def __init__(self, destinos, cert=None, clave=None, ca=None, timeout_s=10):
        self._destinos = destinos
        self._sesion = requests.Session()
        if cert:
            self._sesion.cert = (cert, clave)
            self._sesion.verify = ca
        self._timeout_s = timeout_s

    def reenviar(self, destino, metodo, ruta, query, cuerpo, cabeceras):
        try:
            r = self._sesion.request(metodo, self._destinos[destino] + ruta, params=query,
                                     data=cuerpo, headers=cabeceras, timeout=self._timeout_s)
        except requests.RequestException as exc:
            # El mensaje de la excepcion puede incluir la URL: solo el tipo.
            raise DestinoNoDisponible(type(exc).__name__) from None
        return r.status_code, r.content, r.headers.get("Content-Type", "application/json")


class AuditoriaAsincrona:
    """Fire-and-forget: la respuesta al cliente no espera a Auditoria (VC-003)."""

    def __init__(self, cliente):
        self._cliente = cliente
        self._hilos = ThreadPoolExecutor(max_workers=2, thread_name_prefix="auditoria")

    def registrar(self, registro_auditoria):
        self._hilos.submit(self._enviar, registro_auditoria)

    def _enviar(self, registro_auditoria):
        try:
            self._cliente.registrar(registro_auditoria)
        except Exception as exc:  # noqa: BLE001 - no debe tumbar el gateway
            log.error("evento=auditoria_no_disponible causa=%s", type(exc).__name__)


def _destinos_desde_entorno():
    return {nombre: os.getenv("DESTINO_" + nombre.upper().replace("-", "_"), url)
            for nombre, url in DESTINOS_POR_DEFECTO.items()}


def _reenviador_desde_entorno():
    cert, clave, ca = tls.config_desde_entorno() or (None, None, None)
    return Reenviador(_destinos_desde_entorno(), cert=cert, clave=clave, ca=ca,
                      timeout_s=float(os.getenv("DESTINO_TIMEOUT_S", "10")))


def _llaves_desde_entorno():
    ruta = os.getenv("JWT_PUBLICA_ARCHIVO")
    if not ruta:
        raise SystemExit("Falta JWT_PUBLICA_ARCHIVO")
    return {os.getenv("JWT_KID", "autorizador-v1"): Path(ruta).read_bytes()}


def _buscar_ruta(metodo, ruta):
    for m, patron, nombre, destino, scope in RUTAS:
        if m == metodo and patron.fullmatch(ruta):
            return nombre, destino, scope
    return None


def crear_app(llaves_publicas=None, reenviador=None, auditoria=None,
              extraer_certificado=tls.certificado_cliente):
    llaves_publicas = llaves_publicas or _llaves_desde_entorno()
    reenviador = reenviador or _reenviador_desde_entorno()
    auditoria = auditoria or AuditoriaAsincrona(auditoria_util.desde_entorno(log))
    app = Flask(__name__)

    def rechazar(http, motivo, nombre_ruta, sujeto):
        log.warning("evento=acceso_rechazado ruta=%s sujeto=%s motivo=%s",
                    nombre_ruta, sujeto or "desconocido", motivo)
        auditoria.registrar({
            "marcador": _marcador(), "accion": "ACCESO_RECHAZADO",
            "entidadAfectada": "ApiGateway", "entidadId": nombre_ruta,
            "actorId": sujeto or "desconocido", "resultado": "RECHAZADO", "motivo": motivo,
        })
        respuesta = jsonify({"error": motivo})
        if http == 401:
            respuesta.headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
        return respuesta, http

    @app.get("/salud")
    def salud():
        return jsonify({"ok": True})

    @app.route("/<path:resto>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def enrutar(resto):
        ruta = "/" + resto
        encontrada = _buscar_ruta(request.method, ruta)
        # Un identificador con forma de PAN no se reenvia: acabaria escrito en
        # el access log del microservicio. Los ids reales nunca la tienen (comun/ids.py).
        if encontrada is None or PATRON_PAN.search(ruta):
            return jsonify({"error": "ruta_no_encontrada"}), 404
        nombre_ruta, destino, scope = encontrada

        certificado = extraer_certificado(request.environ)
        if certificado is None:
            return rechazar(401, "sin_certificado", nombre_ruta, None)
        cn, huella = certificado
        autorizacion = request.headers.get("Authorization", "")
        if not autorizacion.startswith("Bearer "):
            return rechazar(401, "token_ausente", nombre_ruta, cn)
        try:
            claims = jwt.validar(autorizacion[len("Bearer "):].strip(), llaves_publicas,
                                 EMISOR, AUDIENCIA, huella)
        except jwt.JWTInvalido as exc:
            return rechazar(401, exc.motivo, nombre_ruta, cn)
        if scope not in jwt.scopes(claims):
            return rechazar(403, "scope_insuficiente", nombre_ruta, claims.get("sub"))

        cabeceras = {"X-Solventa-Sujeto": str(claims.get("sub"))}
        if request.content_type:
            cabeceras["Content-Type"] = request.content_type
        try:
            codigo, cuerpo, tipo = reenviador.reenviar(
                destino, request.method, ruta, list(request.args.items(multi=True)),
                request.get_data(), cabeceras)
        except DestinoNoDisponible as exc:
            log.error("evento=destino_no_disponible ruta=%s destino=%s causa=%s",
                      nombre_ruta, destino, exc)
            return jsonify({"error": "destino_no_disponible"}), 502
        log.info("evento=peticion_enrutada ruta=%s destino=%s sujeto=%s codigo=%s",
                 nombre_ruta, destino, claims.get("sub"), codigo)
        return Response(cuerpo, status=codigo, content_type=tipo)

    if tls.config_desde_entorno() is None:
        log.warning("evento=tls_deshabilitado aviso=solo_para_desarrollo")
    log.info("evento=arranque servicio=api-gateway")
    return app


def _marcador():
    valor = request.headers.get("X-Marcador")
    return valor[:64] if valor else None
