# pagos/tokenizador.py
"""Cliente del Servicio de Tokenizacion, sobre mTLS."""

import requests


class TokenizadorNoDisponible(Exception):
    pass


class PanInvalido(Exception):
    pass


class ClienteTokenizador:
    def __init__(self, url, cert=None, clave=None, ca=None, timeout_s=2.0):
        self._url = url.rstrip("/") + "/tokens"
        self._sesion = requests.Session()
        if cert:
            self._sesion.cert = (cert, clave)
            self._sesion.verify = ca
        self._timeout = timeout_s

    def tokenizar(self, pan):
        """Devuelve (token, ultimos4). El PAN solo viaja en el cuerpo, nunca en la URL."""
        try:
            r = self._sesion.post(self._url, json={"pan": pan}, timeout=self._timeout)
        except requests.RequestException as exc:
            # El mensaje de la excepcion puede incluir la peticion: se conserva
            # solo el tipo.
            raise TokenizadorNoDisponible(type(exc).__name__) from None
        if r.status_code == 400:
            raise PanInvalido()
        if r.status_code not in (200, 201):
            raise TokenizadorNoDisponible("http_%d" % r.status_code)
        datos = r.json()
        return datos["token"], datos["ultimos4"]
