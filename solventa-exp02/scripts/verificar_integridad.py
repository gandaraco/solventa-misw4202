"""Corrida real y reproducible de INTEG-01..05 contra los servicios."""

import base64
import json
import os
import sys
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from comun import jws

SUSCRIPCION = os.getenv("SUSCRIPCION_URL", "http://ms-suscripcion:8080")
AUDITORIA = os.getenv("AUDITORIA_URL", "http://auditoria:8080")
PRIVADA = Path(os.getenv("JWS_PRIVADA_ARCHIVO", "/secretos/consentimiento.key")).read_bytes()
NO_CONFIABLE = Path(os.getenv("JWS_NO_CONFIABLE_ARCHIVO", "/secretos/no_confiable_jws.key")).read_bytes()

# En el compose general los servicios exigen mTLS; en docker-compose.integridad.yml no.
sesion = requests.Session()
if os.getenv("CERT_CLIENTE"):
    sesion.cert = (os.environ["CERT_CLIENTE"], os.environ["CLAVE_CLIENTE"])
    sesion.verify = os.environ["CA_BUNDLE"]


def payload(event_id, suscripcion_id):
    return {"eventId": event_id, "tipo": "CONSENTIMIENTO_OTORGADO",
            "actorId": "harness", "emitidoEn": "2026-09-26T00:00:00+00:00",
            "datos": {"suscripcionId": suscripcion_id}}


def estado(suscripcion_id):
    return sesion.get(SUSCRIPCION + "/suscripciones/" + suscripcion_id, timeout=3).json()


def enviar(event_id, token, marcador):
    return sesion.post(SUSCRIPCION + "/eventos", json={
        "eventId": event_id, "marcador": marcador, "jws": token,
    }, timeout=3)


def alterar(token):
    cabecera, cuerpo, firma = token.split(".")
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    datos["datos"]["suscripcionId"] += "-alterada"
    cuerpo = base64.urlsafe_b64encode(json.dumps(
        datos, sort_keys=True, separators=(",", ":")
    ).encode()).rstrip(b"=").decode()
    return cabecera + "." + cuerpo + "." + firma


def main():
    casos = []

    event_id, sus = "evt-integ-01", "sus-integ-01"
    antes = estado(sus)
    r = enviar(event_id, jws.firmar(payload(event_id, sus), PRIVADA), "INTEG-01")
    despues = estado(sus)
    casos.append(("INTEG-01", r.status_code == 202 and antes["estado"] == "PENDIENTE"
                  and despues["estado"] == "ACTIVA"))

    event_id, sus = "evt-integ-02", "sus-integ-02"
    antes = estado(sus)
    token = alterar(jws.firmar(payload(event_id, sus), PRIVADA))
    r = enviar(event_id, token, "INTEG-02")
    casos.append(("INTEG-02", r.status_code == 422 and estado(sus) == antes))

    event_id, sus = "evt-integ-03", "sus-integ-03"
    antes = estado(sus)
    token = jws.firmar(payload(event_id, sus), NO_CONFIABLE, "impostor-v1")
    r = enviar(event_id, token, "INTEG-03")
    casos.append(("INTEG-03", r.status_code == 422 and estado(sus) == antes))

    event_id, sus = "evt-integ-04", "sus-integ-04"
    antes = estado(sus)
    r = enviar(event_id, "abc.def", "INTEG-04")
    casos.append(("INTEG-04", r.status_code == 422 and estado(sus) == antes))

    event_id, sus = "evt-integ-05", "sus-integ-05"
    antes = estado(sus)
    firmado_para_otro = jws.firmar(payload("evt-original", sus), PRIVADA)
    r = enviar(event_id, firmado_para_otro, "INTEG-05")
    casos.append(("INTEG-05", r.status_code == 422 and estado(sus) == antes))

    for caso, ok in casos:
        registros = sesion.get(AUDITORIA + "/registros?marcador=" + caso,
                                 timeout=3).json()
        ok = ok and len(registros) == 1
        print("%s %s" % ("PASS" if ok else "FAIL", caso))
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
