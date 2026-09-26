import base64
import logging
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from comun import pan as pan_util  # noqa: E402
from pagos.app import crear_app as crear_app_pagos  # noqa: E402
from pagos.almacen import Almacen  # noqa: E402
from pagos.tokenizador import PanInvalido, TokenizadorNoDisponible  # noqa: E402
from tokenizacion.app import crear_app as crear_app_tokenizador  # noqa: E402
from tokenizacion.boveda import Boveda  # noqa: E402

# Valores publicos de prueba de las pasarelas (los mismos de
# harness/fixtures/pans_sinteticos.json). Ninguno es una tarjeta real.
PANS_SINTETICOS = [
    "4111111111111111", "4012888888881881", "5555555555554444", "5105105105105100",
    "378282246310005", "371449635398431", "6011111111111117", "3530111333300000",
    "30569309025904", "4222222222222", "4111111111111111110",
]


def sin_pan(contenido, pans=PANS_SINTETICOS):
    """True si en `contenido` no aparece ningun PAN, ni por patron ni literal."""
    if isinstance(contenido, bytes):
        contenido = contenido.decode("latin-1")
    return not pan_util.buscar(contenido) and not any(p in contenido for p in pans)


def _llave():
    return base64.urlsafe_b64encode(os.urandom(32))


@pytest.fixture
def boveda(tmp_path):
    return Boveda("sqlite:///%s" % (tmp_path / "boveda.db"), _llave(), _llave())


@pytest.fixture
def tokenizador(boveda):
    app = crear_app_tokenizador(boveda)
    app.testing = True
    return app.test_client()


class TokenizadorEnProceso:
    """Adapta el cliente de pruebas de Flask a la interfaz de ClienteTokenizador."""

    def __init__(self, cliente):
        self.cliente = cliente
        self.llamadas = 0

    def tokenizar(self, pan):
        self.llamadas += 1
        r = self.cliente.post("/tokens", json={"pan": pan})
        if r.status_code == 400:
            raise PanInvalido()
        if r.status_code not in (200, 201):
            raise TokenizadorNoDisponible("http_%d" % r.status_code)
        return r.get_json()["token"], r.get_json()["ultimos4"]


class TokenizadorCaido:
    llamadas = 0

    def tokenizar(self, pan):
        self.llamadas += 1
        raise TokenizadorNoDisponible("ConnectionError")


@pytest.fixture
def ruta_bd_pagos(tmp_path):
    return tmp_path / "pagos.db"


@pytest.fixture
def tokenizador_en_proceso(tokenizador):
    return TokenizadorEnProceso(tokenizador)


@pytest.fixture
def pagos(ruta_bd_pagos, tokenizador_en_proceso):
    app = crear_app_pagos(Almacen("sqlite:///%s" % ruta_bd_pagos), tokenizador_en_proceso)
    app.testing = True
    return app.test_client()


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog
