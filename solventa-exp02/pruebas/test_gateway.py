"""API Gateway y Autorizador: mTLS + JWT ligado al certificado (RFC 8705)."""

import ssl
import threading
import time

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

import generar_material
from autorizador.app import crear_app as crear_autorizador
from comun import jws, jwt, tls
from gateway.app import (AUDIENCIA, EMISOR, DestinoNoDisponible, Reenviador,
                         crear_app as crear_gateway)

SCOPES = ["pagos:escribir", "pagos:leer", "consentimientos:escribir", "suscripciones:leer"]
HARNESS = ("harness", "huella-harness")
ATACANTE = ("atacante", "huella-atacante")


def _par():
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (privada.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()),
            privada.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo))


def _certificado_de_prueba(environ):
    # En produccion lo lee comun/tls.py del socket TLS; aqui lo inyecta la prueba.
    return environ.get("prueba.certificado")


class ReenviadorFalso:
    def __init__(self, caido=False):
        self.llamadas = []
        self.caido = caido

    def reenviar(self, destino, metodo, ruta, query, cuerpo, cabeceras):
        if self.caido:
            raise DestinoNoDisponible("ConnectionError")
        self.llamadas.append(dict(destino=destino, metodo=metodo, ruta=ruta, query=query,
                                  cuerpo=cuerpo, cabeceras=cabeceras))
        return 201, b'{"ok":true}', "application/json"


class AuditoriaEnMemoria:
    def __init__(self):
        self.registros = []

    def registrar(self, registro):
        self.registros.append(registro)


@pytest.fixture(scope="module")
def llaves():
    return _par()


@pytest.fixture
def autorizador(llaves):
    app = crear_autorizador(llaves[0], {"harness": SCOPES}, _certificado_de_prueba)
    app.testing = True
    return app.test_client()


@pytest.fixture
def entorno(llaves):
    reenviador, auditoria = ReenviadorFalso(), AuditoriaEnMemoria()
    app = crear_gateway({"autorizador-v1": llaves[1]}, reenviador, auditoria,
                        _certificado_de_prueba)
    app.testing = True
    return app.test_client(), reenviador, auditoria


def _token(autorizador, certificado=HARNESS, **datos):
    datos.setdefault("grant_type", "client_credentials")
    return autorizador.post("/oauth/token", data=datos,
                            environ_base={"prueba.certificado": certificado})


def _emitir(llave, huella="huella-harness", scopes=SCOPES, audiencia=AUDIENCIA, ahora=None):
    return jwt.emitir("harness", scopes, huella, llave, "autorizador-v1", EMISOR, audiencia,
                      ahora=ahora)


def _pedir(cliente, token=None, certificado=HARNESS, metodo="POST", ruta="/pagos", **kwargs):
    cabeceras = {"Authorization": "Bearer " + token} if token else {}
    cabeceras.update(kwargs.pop("headers", {}))
    return cliente.open(ruta, method=metodo, headers=cabeceras,
                        environ_base={"prueba.certificado": certificado}, **kwargs)


# --- Autorizador ---------------------------------------------------------------

def test_autorizador_emite_token_ligado_al_certificado(autorizador, llaves):
    r = _token(autorizador)
    assert r.status_code == 200
    cuerpo = r.get_json()
    claims = jws.verificar(cuerpo["access_token"], {"autorizador-v1": llaves[1]})
    assert claims["sub"] == "harness" and claims["aud"] == AUDIENCIA and claims["iss"] == EMISOR
    assert claims["cnf"] == {"x5t#S256": "huella-harness"}
    assert set(claims["scope"].split()) == set(SCOPES)
    assert cuerpo["token_type"] == "Bearer" and cuerpo["expires_in"] == 300


def test_autorizador_entrega_solo_los_scopes_pedidos(autorizador):
    assert _token(autorizador, scope="pagos:leer").get_json()["scope"] == "pagos:leer"


@pytest.mark.parametrize("certificado,datos,codigo,error", [
    (None, {}, 401, "invalid_client"),
    (ATACANTE, {}, 401, "invalid_client"),
    (HARNESS, {"grant_type": "password"}, 400, "unsupported_grant_type"),
    (HARNESS, {"scope": "pagos:escribir auditoria:borrar"}, 400, "invalid_scope"),
])
def test_autorizador_rechaza(autorizador, certificado, datos, codigo, error):
    r = _token(autorizador, certificado, **datos)
    assert r.status_code == codigo and r.get_json()["error"] == error
    assert "access_token" not in r.get_json()


# --- Gateway ---------------------------------------------------------------------

def test_reenvia_con_token_valido_sin_el_token(entorno, autorizador):
    cliente, reenviador, _ = entorno
    token = _token(autorizador).get_json()["access_token"]
    r = _pedir(cliente, token, json={"monto": 1}, query_string={"referencia": "x"})
    assert r.status_code == 201 and r.get_json() == {"ok": True}
    llamada = reenviador.llamadas[0]
    assert (llamada["destino"], llamada["metodo"], llamada["ruta"]) == ("ms-pagos", "POST", "/pagos")
    assert llamada["query"] == [("referencia", "x")]
    assert llamada["cuerpo"] == b'{"monto": 1}'
    assert "Authorization" not in llamada["cabeceras"]
    assert llamada["cabeceras"]["X-Solventa-Sujeto"] == "harness"


@pytest.mark.parametrize("metodo,ruta,destino", [
    ("GET", "/pagos", "ms-pagos"), ("GET", "/pagos/pag_abc-1", "ms-pagos"),
    ("POST", "/consentimientos", "ms-consentimiento"),
    ("GET", "/suscripciones/sus-1", "ms-suscripcion"),
])
def test_tabla_de_rutas(entorno, llaves, metodo, ruta, destino):
    cliente, reenviador, _ = entorno
    assert _pedir(cliente, _emitir(llaves[0]), metodo=metodo, ruta=ruta).status_code == 201
    assert reenviador.llamadas[0]["destino"] == destino


def test_sin_token_401_y_auditado(entorno):
    cliente, reenviador, auditoria = entorno
    r = _pedir(cliente, headers={"X-Marcador": "M-1"})
    assert r.status_code == 401 and r.get_json() == {"error": "token_ausente"}
    assert r.headers["WWW-Authenticate"].startswith("Bearer")
    assert not reenviador.llamadas
    registro = auditoria.registros[0]
    assert (registro["accion"], registro["resultado"], registro["motivo"], registro["marcador"]) == \
        ("ACCESO_RECHAZADO", "RECHAZADO", "token_ausente", "M-1")


def test_token_robado_con_otro_certificado(entorno, llaves):
    cliente, reenviador, _ = entorno
    r = _pedir(cliente, _emitir(llaves[0]), certificado=ATACANTE)
    assert r.status_code == 401 and r.get_json()["error"] == "certificado_no_coincide"
    assert not reenviador.llamadas


def test_token_expirado(entorno, llaves):
    cliente, _, _ = entorno
    r = _pedir(cliente, _emitir(llaves[0], ahora=time.time() - 1000))
    assert r.status_code == 401 and r.get_json()["error"] == "token_expirado"


def test_token_para_otra_audiencia(entorno, llaves):
    cliente, _, _ = entorno
    r = _pedir(cliente, _emitir(llaves[0], audiencia="otro-servicio"))
    assert r.status_code == 401 and r.get_json()["error"] == "audiencia_invalida"


def test_token_firmado_con_otra_llave(entorno):
    cliente, _, _ = entorno
    r = _pedir(cliente, _emitir(_par()[0]))
    assert r.status_code == 401 and r.get_json()["error"] == "firma_invalida"


def test_scope_insuficiente_403(entorno, llaves):
    cliente, reenviador, auditoria = entorno
    r = _pedir(cliente, _emitir(llaves[0], scopes=["pagos:leer"]))
    assert r.status_code == 403 and r.get_json()["error"] == "scope_insuficiente"
    assert not reenviador.llamadas and auditoria.registros[0]["actorId"] == "harness"


@pytest.mark.parametrize("metodo,ruta", [
    ("POST", "/tokens"), ("GET", "/registros"), ("DELETE", "/pagos"),
    ("GET", "/pagos/4111111111111111"), ("GET", "/pagos/4111-1111-1111-1111"),
])
def test_ruta_desconocida_o_con_pan_no_se_reenvia(entorno, llaves, metodo, ruta):
    cliente, reenviador, _ = entorno
    r = _pedir(cliente, _emitir(llaves[0]), metodo=metodo, ruta=ruta)
    assert r.status_code == 404 and not reenviador.llamadas
    assert b"4111" not in r.data


def test_destino_caido_502(llaves):
    app = crear_gateway({"autorizador-v1": llaves[1]}, ReenviadorFalso(caido=True),
                        AuditoriaEnMemoria(), _certificado_de_prueba)
    r = _pedir(app.test_client(), _emitir(llaves[0]))
    assert r.status_code == 502 and r.get_json() == {"error": "destino_no_disponible"}


def test_reenviador_real_traduce_errores_de_red():
    reenviador = Reenviador({"ms-pagos": "http://127.0.0.1:9"}, timeout_s=1)
    with pytest.raises(DestinoNoDisponible) as exc:
        reenviador.reenviar("ms-pagos", "GET", "/pagos", [("pan", "4111111111111111")], b"", {})
    assert "4111" not in str(exc.value)


# --- Identidad del cliente desde el socket TLS -------------------------------------

@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    d = tmp_path_factory.mktemp("certs_gw")
    generar_material.generar_certs(d)
    return d


def test_certificado_cliente_se_lee_del_socket_tls(certs):
    app = Flask(__name__)

    @app.get("/quien")
    def quien():
        return jsonify(tls.certificado_cliente(request.environ))

    ctx = tls.contexto_servidor(certs / "api-gateway.crt", certs / "api-gateway.key", certs / "ca.crt")
    srv = make_server("localhost", 0, app, threaded=True, ssl_context=ctx)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = requests.get("https://localhost:%d/quien" % srv.server_port, timeout=5,
                         cert=(str(certs / "harness.crt"), str(certs / "harness.key")),
                         verify=str(certs / "ca.crt"))
    finally:
        srv.shutdown()
    esperado = tls.huella_certificado(ssl.PEM_cert_to_DER_cert((certs / "harness.crt").read_text()))
    assert r.json() == ["harness", esperado]


def test_sin_socket_tls_no_hay_certificado():
    assert tls.certificado_cliente({}) is None
