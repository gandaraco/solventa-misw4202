"""mTLS real entre MS Pagos y el tokenizador, con el mismo contexto que usa gunicorn."""

import socket
import ssl
import threading

import pytest
import requests
from werkzeug.serving import make_server

import generar_material
from comun import tls
from pagos.tokenizador import ClienteTokenizador, TokenizadorNoDisponible
from tokenizacion.app import crear_app


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    d = tmp_path_factory.mktemp("certs")
    generar_material.generar_certs(d)
    return d


@pytest.fixture
def servidor(certs, boveda):
    ctx = tls.contexto_servidor(certs / "tokenizador.crt", certs / "tokenizador.key", certs / "ca.crt")
    srv = make_server("localhost", 0, crear_app(boveda), threaded=True, ssl_context=ctx)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield "https://localhost:%d" % srv.server_port
    srv.shutdown()


def _cliente(certs, url, nombre="ms-pagos"):
    return ClienteTokenizador(url, cert=str(certs / (nombre + ".crt")),
                              clave=str(certs / (nombre + ".key")), ca=str(certs / "ca.crt"))


def test_con_certificado_valido_tokeniza(certs, servidor):
    token, ultimos4 = _cliente(certs, servidor).tokenizar("4111111111111111")
    assert token.startswith("tok_") and ultimos4 == "1111"


def test_sin_certificado_de_cliente_se_rechaza(certs, servidor):
    with pytest.raises(requests.exceptions.SSLError):
        requests.post(servidor + "/tokens", json={"pan": "4111111111111111"},
                      verify=str(certs / "ca.crt"), timeout=5)


def test_certificado_de_otra_ca_se_rechaza(certs, servidor):
    with pytest.raises(TokenizadorNoDisponible):
        _cliente(certs, servidor, "no_confiable").tokenizar("4111111111111111")


def test_tls_12_se_rechaza(certs, servidor):
    ctx = ssl.create_default_context(cafile=str(certs / "ca.crt"))
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(certs / "ms-pagos.crt"), str(certs / "ms-pagos.key"))
    host, puerto = servidor.removeprefix("https://").split(":")
    with socket.create_connection((host, int(puerto)), timeout=5) as s:
        with pytest.raises(ssl.SSLError):
            ctx.wrap_socket(s, server_hostname=host)


def test_cliente_rechaza_servidor_no_confiable(certs, servidor, tmp_path):
    # MS Pagos no le entrega el PAN a un servidor que no presente un
    # certificado de la CA del experimento (p. ej. un mitmproxy en el medio).
    otra = tmp_path / "otra"
    generar_material.generar_certs(otra)
    cliente = ClienteTokenizador(servidor, cert=str(certs / "ms-pagos.crt"),
                                 clave=str(certs / "ms-pagos.key"), ca=str(otra / "ca.crt"))
    with pytest.raises(TokenizadorNoDisponible):
        cliente.tokenizar("4111111111111111")
