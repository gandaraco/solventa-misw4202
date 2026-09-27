"""Cliente pequeno del Servicio de Auditoria."""

import os

import requests

from comun import tls


class AuditoriaNoDisponible(RuntimeError):
    pass


class ClienteAuditoria:
    def __init__(self, url, timeout_s=2, cert=None, clave=None, ca=None):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self._sesion = requests.Session()
        if cert:
            # mTLS: el servicio se identifica con su propio certificado.
            self._sesion.cert = (cert, clave)
            self._sesion.verify = ca

    def registrar(self, registro):
        try:
            respuesta = self._sesion.post(self.url + "/registros", json=registro,
                                          timeout=self.timeout_s)
            respuesta.raise_for_status()
            return respuesta.json()
        except requests.RequestException as exc:
            raise AuditoriaNoDisponible(type(exc).__name__) from exc


def desde_entorno(log):
    """ClienteAuditoria si hay AUDITORIA_URL (con mTLS si TLS_* esta definido); si no, el log."""
    url = os.getenv("AUDITORIA_URL")
    if not url:
        return AuditoriaLog(log)
    cert, clave, ca = tls.config_desde_entorno() or (None, None, None)
    return ClienteAuditoria(url, cert=cert, clave=clave, ca=ca)


class AuditoriaLog:
    """Respaldo explicito para desarrollo; conserva el contrato sin red."""

    def __init__(self, log):
        self.log = log

    def registrar(self, registro):
        self.log.info(
            "evento=auditoria accion=%s entidad=%s entidadId=%s actorId=%s resultado=%s motivo=%s",
            registro.get("accion", ""), registro.get("entidadAfectada", ""),
            registro.get("entidadId", ""), registro.get("actorId", ""),
            registro.get("resultado", ""), registro.get("motivo", ""),
        )
        return registro
