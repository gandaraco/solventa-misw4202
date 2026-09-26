import base64
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from auditoria.almacen import AlmacenAuditoria
from auditoria.app import crear_app as crear_app_auditoria
from comun import jws
from consentimiento.app import crear_app as crear_app_consentimiento
from suscripcion.almacen import AlmacenSuscripcion
from suscripcion.app import crear_app as crear_app_suscripcion


def _par():
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        privada.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()),
        privada.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo),
    )


class AuditoriaEnProceso:
    def __init__(self, cliente):
        self.cliente = cliente

    def registrar(self, registro):
        respuesta = self.cliente.post("/registros", json=registro)
        assert respuesta.status_code == 201
        return respuesta.get_json()


@pytest.fixture
def entorno_integridad(tmp_path):
    privada, publica = _par()
    almacen_auditoria = AlmacenAuditoria("sqlite:///%s" % (tmp_path / "auditoria.db"))
    app_auditoria = crear_app_auditoria(almacen_auditoria)
    app_auditoria.testing = True
    auditoria = app_auditoria.test_client()
    almacen_suscripcion = AlmacenSuscripcion("sqlite:///%s" % (tmp_path / "suscripcion.db"))
    app_suscripcion = crear_app_suscripcion(
        almacen_suscripcion, {"consentimiento-v1": publica}, AuditoriaEnProceso(auditoria))
    app_suscripcion.testing = True
    app_consentimiento = crear_app_consentimiento(privada)
    app_consentimiento.testing = True
    return {
        "privada": privada, "publica": publica, "auditoria": auditoria,
        "suscripcion": app_suscripcion.test_client(),
        "consentimiento": app_consentimiento.test_client(),
    }


def _sobre(entorno, suscripcion_id="sus-prueba", marcador="EXP02-JWS"):
    respuesta = entorno["consentimiento"].post("/consentimientos", json={
        "suscripcionId": suscripcion_id, "actorId": "cliente-prueba",
        "marcador": marcador,
    })
    assert respuesta.status_code == 201
    cuerpo = respuesta.get_json()
    return {"eventId": cuerpo["eventId"], "marcador": cuerpo["marcador"],
            "jws": cuerpo["jws"]}


def _auditoria(entorno, event_id):
    return entorno["auditoria"].get("/registros?eventId=" + event_id).get_json()


def _estado(entorno, suscripcion_id="sus-prueba"):
    return entorno["suscripcion"].get("/suscripciones/" + suscripcion_id).get_json()


def _alterar_payload(token):
    cabecera, payload, firma = token.split(".")
    datos = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    datos["datos"]["suscripcionId"] = "sus-alterada"
    nuevo = base64.urlsafe_b64encode(json.dumps(
        datos, sort_keys=True, separators=(",", ":")
    ).encode()).rstrip(b"=").decode()
    return cabecera + "." + nuevo + "." + firma


def test_integ_01_jws_valido_se_procesa_y_audita(entorno_integridad):
    e = entorno_integridad
    sobre = _sobre(e)
    assert _estado(e)["estado"] == "PENDIENTE"
    respuesta = e["suscripcion"].post("/eventos", json=sobre)
    assert respuesta.status_code == 202
    assert _estado(e)["estado"] == "ACTIVA"
    registros = _auditoria(e, sobre["eventId"])
    assert len(registros) == 1
    assert registros[0]["resultado"] == "ACEPTADO"
    assert len(registros[0]["hashIntegridad"]) == 64


def test_integ_02_payload_alterado_se_rechaza_antes_del_estado(entorno_integridad):
    e = entorno_integridad
    sobre = _sobre(e)
    antes = _estado(e)
    sobre["jws"] = _alterar_payload(sobre["jws"])
    respuesta = e["suscripcion"].post("/eventos", json=sobre)
    assert respuesta.status_code == 422
    assert respuesta.get_json()["motivo"] == "firma_invalida"
    assert _estado(e) == antes
    assert _auditoria(e, sobre["eventId"])[0]["resultado"] == "RECHAZADO"


def test_integ_03_clave_no_confiable_se_rechaza(entorno_integridad):
    e = entorno_integridad
    privada_otra, _ = _par()
    event_id = "evt-clave-no-confiable"
    token = jws.firmar({"eventId": event_id, "tipo": "CONSENTIMIENTO_OTORGADO",
                        "datos": {"suscripcionId": "sus-prueba"}},
                       privada_otra, "impostor-v1")
    respuesta = e["suscripcion"].post("/eventos", json={"eventId": event_id, "jws": token})
    assert respuesta.status_code == 422
    assert respuesta.get_json()["motivo"] == "clave_no_confiable"
    assert _estado(e)["estado"] == "PENDIENTE"


@pytest.mark.parametrize("token,motivo", [(None, "firma_ausente"),
                                            ("abc.def", "firma_truncada")])
def test_integ_04_firma_ausente_o_truncada(token, motivo, entorno_integridad):
    e = entorno_integridad
    event_id = "evt-firma-incompleta"
    respuesta = e["suscripcion"].post("/eventos", json={"eventId": event_id, "jws": token})
    assert respuesta.status_code == 422
    assert respuesta.get_json()["motivo"] == motivo
    assert _estado(e)["estado"] == "PENDIENTE"


def test_integ_05_firma_reutilizada_sobre_otro_payload(entorno_integridad):
    e = entorno_integridad
    sobre = _sobre(e)
    sobre["jws"] = _alterar_payload(sobre["jws"])
    respuesta = e["suscripcion"].post("/eventos", json=sobre)
    assert respuesta.status_code == 422
    assert _estado(e)["estado"] == "PENDIENTE"


def test_cadena_de_auditoria_enlaza_registros(entorno_integridad):
    e = entorno_integridad
    primero = _sobre(e, "sus-uno", "M-1")
    segundo = _sobre(e, "sus-dos", "M-2")
    assert e["suscripcion"].post("/eventos", json=primero).status_code == 202
    assert e["suscripcion"].post("/eventos", json=segundo).status_code == 202
    registros = e["auditoria"].get("/registros").get_json()
    assert registros[0]["hashAnterior"] == "0" * 64
    assert registros[1]["hashAnterior"] == registros[0]["hashIntegridad"]


def test_jws_no_acepta_algoritmo_none(entorno_integridad):
    cabecera = base64.urlsafe_b64encode(b'{"alg":"none","kid":"consentimiento-v1"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(b'{"eventId":"evt"}').rstrip(b"=").decode()
    with pytest.raises(jws.JWSInvalido, match="algoritmo_no_permitido"):
        jws.verificar(cabecera + "." + payload + ".x",
                      {"consentimiento-v1": entorno_integridad["publica"]})
