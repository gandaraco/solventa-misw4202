"""Transporte Kafka: el mismo sobre JWS del productor llega intacto al procesador.

Un broker en memoria sustituye a Kafka; la corrida real contra el broker con
mTLS esta en scripts/verificar_infraestructura.py.
"""

import base64
import json

import pytest

from auditoria.almacen import AlmacenAuditoria
from auditoria.app import crear_app as crear_app_auditoria
from comun import kafka
from consentimiento.app import crear_app as crear_app_consentimiento
from suscripcion.almacen import AlmacenSuscripcion
from suscripcion.app import crear_app as crear_app_suscripcion
from test_integridad import AuditoriaEnProceso, _par

TOPICO = "solventa.consentimiento.eventos"


class Mensaje:
    def __init__(self, valor, offset=0, error=None, topico=TOPICO):
        self._valor, self._offset, self._error, self._topico = valor, offset, error, topico

    def value(self):
        return self._valor

    def offset(self):
        return self._offset

    def partition(self):
        return 0

    def topic(self):
        return self._topico

    def error(self):
        return self._error


class ErrorKafka:
    def __init__(self, nombre):
        self._nombre = nombre

    def name(self):
        return self._nombre


class Broker:
    """Productor y consumidor en memoria con la interfaz de confluent_kafka."""

    def __init__(self, error_entrega=None, sin_confirmacion=False):
        self.mensajes, self.pendientes, self.confirmados, self.retrocesos = [], [], [], []
        self.error_entrega, self.sin_confirmacion = error_entrega, sin_confirmacion
        self.leido = 0

    # Productor
    def produce(self, topico, value, key=None, on_delivery=None):
        self.pendientes.append((Mensaje(value, len(self.mensajes), topico=topico), key, on_delivery))
        self.mensajes.append(value)

    def flush(self, timeout):
        if not self.sin_confirmacion:
            for mensaje, _, confirmar in self.pendientes:
                confirmar(self.error_entrega, mensaje)
        self.pendientes = []
        return 0

    # Consumidor
    def subscribe(self, topicos):
        self.topicos = topicos

    def poll(self, timeout):
        if self.leido >= len(self.mensajes):
            return None
        mensaje = Mensaje(self.mensajes[self.leido], self.leido)
        self.leido += 1
        return mensaje

    def commit(self, message, asynchronous):
        self.confirmados.append(message.offset())

    def seek(self, particion):
        self.retrocesos.append(particion.offset)
        self.leido = particion.offset

    def close(self):
        pass


class Registro:
    def __init__(self):
        self.lineas = []

    def info(self, formato, *args):
        self.lineas.append(formato % args)

    warning = error = info


# --- Configuracion ---------------------------------------------------------------

def test_sin_bootstrap_no_hay_kafka(monkeypatch):
    monkeypatch.delenv("KAFKA_BOOTSTRAP", raising=False)
    assert kafka.config_desde_entorno() is None


def test_kafka_sin_tls_no_arranca(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "kafka:9092")
    for variable in ("TLS_CERT", "TLS_CLAVE", "TLS_CA"):
        monkeypatch.delenv(variable, raising=False)
    with pytest.raises(SystemExit):
        kafka.config_desde_entorno()


def test_kafka_con_mtls(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "kafka:9092")
    monkeypatch.setenv("TLS_CERT", "/certs/x.crt")
    monkeypatch.setenv("TLS_CLAVE", "/certs/x.key")
    monkeypatch.setenv("TLS_CA", "/certs/ca.crt")
    cfg = kafka.config_desde_entorno()
    assert cfg["security.protocol"] == "SSL"
    assert cfg["ssl.certificate.location"] == "/certs/x.crt"
    assert cfg["ssl.ca.location"] == "/certs/ca.crt"
    assert cfg["ssl.endpoint.identification.algorithm"] == "https"


# --- Publicador ---------------------------------------------------------------------

def test_publicador_espera_confirmacion():
    broker = Broker()
    resultado = kafka.PublicadorKafka({}, TOPICO, productor=broker).publicar(
        {"eventId": "evt_1", "marcador": None, "jws": "a.b.c"})
    assert resultado == {"topico": TOPICO, "particion": 0, "offset": 0}
    assert json.loads(broker.mensajes[0]) == {"eventId": "evt_1", "marcador": None, "jws": "a.b.c"}
    assert broker.pendientes == []


@pytest.mark.parametrize("broker,motivo", [
    (Broker(error_entrega=ErrorKafka("_MSG_TIMED_OUT")), "_MSG_TIMED_OUT"),
    (Broker(sin_confirmacion=True), "sin_confirmacion"),
])
def test_publicador_sin_confirmacion_falla(broker, motivo):
    with pytest.raises(kafka.PublicacionFallida, match=motivo):
        kafka.PublicadorKafka({}, TOPICO, productor=broker).publicar({"eventId": "evt_1"})


def test_consentimiento_responde_503_si_kafka_no_confirma():
    privada, _ = _par()
    publicador = kafka.PublicadorKafka({}, TOPICO, productor=Broker(sin_confirmacion=True))
    app = crear_app_consentimiento(privada, publicador)
    r = app.test_client().post("/consentimientos", json={"suscripcionId": "s", "actorId": "a"})
    assert r.status_code == 503 and r.get_json()["error"] == "consumidor_no_disponible"


# --- Consumidor ---------------------------------------------------------------------

def test_consumidor_confirma_despues_de_procesar():
    broker, recibidos = Broker(), []
    broker.mensajes = [b'{"eventId":"evt_1"}', b"no es json", b"[1,2]"]
    consumidor = kafka.ConsumidorKafka({}, TOPICO, "g", recibidos.append, Registro(), broker)
    while consumidor.procesar_uno(0):
        pass
    assert recibidos == [{"eventId": "evt_1"}, {}, {}]
    assert broker.confirmados == [0, 1, 2]


def test_consumidor_reintenta_si_el_procesador_falla():
    broker, intentos = Broker(), []

    def manejador(sobre):
        intentos.append(sobre)
        if len(intentos) == 1:
            raise RuntimeError("auditoria caida")

    broker.mensajes = [b'{"eventId":"evt_1"}']
    consumidor = kafka.ConsumidorKafka({}, TOPICO, "g", manejador, Registro(), broker,
                                       espera_reintento_s=0)
    assert consumidor.procesar_uno(0) is False
    assert broker.confirmados == [] and broker.retrocesos == [0]
    assert consumidor.procesar_uno(0) is True
    assert len(intentos) == 2 and broker.confirmados == [0]


def test_consumidor_ignora_errores_del_broker():
    broker, recibidos = Broker(), []
    consumidor = kafka.ConsumidorKafka({}, TOPICO, "g", recibidos.append, Registro(), broker)
    broker.poll = lambda timeout: Mensaje(None, error=ErrorKafka("_TRANSPORT"))
    assert consumidor.procesar_uno(0) is False and recibidos == []


# --- Extremo a extremo con el broker en memoria ------------------------------------

@pytest.fixture
def cadena(tmp_path):
    privada, publica = _par()
    broker = Broker()
    auditoria = crear_app_auditoria(AlmacenAuditoria("sqlite:///%s" % (tmp_path / "a.db")))
    auditoria.testing = True
    auditoria = auditoria.test_client()
    suscripcion = crear_app_suscripcion(
        AlmacenSuscripcion("sqlite:///%s" % (tmp_path / "s.db")),
        {"consentimiento-v1": publica}, AuditoriaEnProceso(auditoria))
    consentimiento = crear_app_consentimiento(
        privada, kafka.PublicadorKafka({}, TOPICO, productor=broker))
    consumidor = kafka.ConsumidorKafka({}, TOPICO, "ms-suscripcion",
                                       suscripcion.extensions["procesar_sobre"], Registro(), broker)
    return {"broker": broker, "consumidor": consumidor, "auditoria": auditoria,
            "suscripcion": suscripcion.test_client(), "consentimiento": consentimiento.test_client()}


def _estado(c, sid):
    return c["suscripcion"].get("/suscripciones/" + sid).get_json()


def test_evento_valido_viaja_por_kafka_y_activa(cadena):
    r = cadena["consentimiento"].post("/consentimientos", json={
        "suscripcionId": "sus-k", "actorId": "cliente", "marcador": "K-1"})
    assert r.status_code == 201 and r.get_json()["resultado"]["topico"] == TOPICO
    assert _estado(cadena, "sus-k")["estado"] == "PENDIENTE"
    assert cadena["consumidor"].procesar_uno(0)
    assert _estado(cadena, "sus-k")["estado"] == "ACTIVA"
    registros = cadena["auditoria"].get("/registros?marcador=K-1").get_json()
    assert [x["resultado"] for x in registros] == ["ACEPTADO"]


def test_sobre_alterado_en_el_topico_se_rechaza_sin_cambiar_estado(cadena):
    cadena["consentimiento"].post("/consentimientos", json={
        "suscripcionId": "sus-k", "actorId": "cliente", "marcador": "K-1"})
    sobre = json.loads(cadena["broker"].mensajes.pop())
    cabecera, cuerpo, firma = sobre["jws"].split(".")
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    datos["datos"]["suscripcionId"] = "sus-victima"
    cuerpo = base64.urlsafe_b64encode(json.dumps(datos).encode()).rstrip(b"=").decode()
    sobre.update(jws=cabecera + "." + cuerpo + "." + firma, marcador="K-ALTERADO")
    cadena["broker"].mensajes.append(json.dumps(sobre).encode())

    antes = _estado(cadena, "sus-victima")
    assert cadena["consumidor"].procesar_uno(0)
    assert _estado(cadena, "sus-victima") == antes
    registro = cadena["auditoria"].get("/registros?marcador=K-ALTERADO").get_json()[0]
    assert (registro["resultado"], registro["motivo"]) == ("RECHAZADO", "firma_invalida")
    # Rechazado y auditado: el offset se confirma para no reprocesar el ataque.
    assert cadena["broker"].confirmados == [0]
