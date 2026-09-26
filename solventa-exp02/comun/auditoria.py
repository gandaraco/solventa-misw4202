"""Cliente pequeno del Servicio de Auditoria."""

import requests


class AuditoriaNoDisponible(RuntimeError):
    pass


class ClienteAuditoria:
    def __init__(self, url, timeout_s=2):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def registrar(self, registro):
        try:
            respuesta = requests.post(self.url + "/registros", json=registro,
                                      timeout=self.timeout_s)
            respuesta.raise_for_status()
            return respuesta.json()
        except requests.RequestException as exc:
            raise AuditoriaNoDisponible(type(exc).__name__) from exc


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
