import sqlite3

import pytest

from conftest import PANS_SINTETICOS, TokenizadorCaido, sin_pan
from pagos.almacen import Almacen
from pagos.app import crear_app

PAGO = {"monto": 150000, "moneda": "COP", "concepto": "prima", "polizaId": "pol-1"}


def _pagar(cliente, pan="4111111111111111", **extra):
    return cliente.post("/pagos", json=dict(PAGO, pan=pan, **extra))


def _volcado(ruta):
    """Todo el contenido de la base, fila por fila, como texto."""
    cx = sqlite3.connect(ruta)
    return "\n".join(line for line in cx.iterdump())


def _filas(ruta):
    return sqlite3.connect(ruta).execute("SELECT COUNT(*) FROM pagos").fetchone()[0]


def test_registra_pago_con_token(pagos):
    r = _pagar(pagos, referencia="EXP02-PAN-A1")
    assert r.status_code == 201
    cuerpo = r.get_json()
    assert cuerpo["tokenTarjeta"].startswith("tok_")
    assert cuerpo["ultimos4"] == "1111"
    assert cuerpo["monto"] == "150000.00"
    assert cuerpo["estado"] == "registrado"
    assert sin_pan(r.data)

    consulta = pagos.get("/pagos/" + cuerpo["pagoId"])
    assert consulta.get_json() == cuerpo
    assert pagos.get("/pagos?referencia=EXP02-PAN-A1").get_json() == [cuerpo]


def test_almacen_sin_pan_tras_todos_los_sinteticos(pagos, ruta_bd_pagos):
    for i, pan in enumerate(PANS_SINTETICOS):
        assert _pagar(pagos, pan=pan, referencia="ref-%d" % i).status_code == 201
    volcado = _volcado(ruta_bd_pagos)
    # Control positivo: si no se guardo nada, "cero PAN" no demostraria nada.
    assert _filas(ruta_bd_pagos) == len(PANS_SINTETICOS)
    assert sin_pan(volcado)
    crudo = ruta_bd_pagos.read_bytes()  # incluye paginas libres y el journal
    assert not any(pan.encode() in crudo for pan in PANS_SINTETICOS)


def test_misma_tarjeta_mismo_token_entre_pagos(pagos):
    a = _pagar(pagos).get_json()
    b = _pagar(pagos, pan="4111 1111 1111 1111").get_json()
    assert a["tokenTarjeta"] == b["tokenTarjeta"]
    assert a["pagoId"] != b["pagoId"]


def test_campos_extra_no_se_persisten(pagos, ruta_bd_pagos):
    r = _pagar(pagos, nota="tarjeta 5555555555554444", pan_copia="4111111111111111")
    assert r.status_code == 201
    assert sin_pan(_volcado(ruta_bd_pagos))


def test_logs_sin_pan(pagos, logs):
    for pan in PANS_SINTETICOS:
        _pagar(pagos, pan=pan)
    _pagar(pagos, pan="4111111111111112")
    assert "evento=pago_registrado" in logs.text
    assert "evento=auditoria accion=PAGO_REGISTRADO" in logs.text
    assert sin_pan(logs.text, PANS_SINTETICOS + ["4111111111111112"])


def test_pan_invalido_no_persiste(pagos, ruta_bd_pagos):
    r = _pagar(pagos, pan="4111111111111112")
    assert r.status_code == 400
    assert r.get_json() == {"error": "pan_invalido"}
    assert _filas(ruta_bd_pagos) == 0


@pytest.mark.parametrize("cambio,error", [
    ({"monto": -5}, "monto_invalido"),
    ({"monto": "abc"}, "monto_invalido"),
    ({"monto": "NaN"}, "monto_invalido"),
    ({"concepto": "otro"}, "concepto_invalido"),
    ({"moneda": "PESOS"}, "moneda_invalida"),
    ({"pan": None}, "pan_invalido"),
])
def test_peticion_invalida_no_llega_al_tokenizador(pagos, tokenizador_en_proceso, cambio, error):
    r = pagos.post("/pagos", json={**PAGO, "pan": "4111111111111111", **cambio})
    assert r.status_code == 400
    assert r.get_json() == {"error": error}
    assert tokenizador_en_proceso.llamadas == 0


def test_tokenizador_caido_no_persiste_nada(ruta_bd_pagos, logs):
    app = crear_app(Almacen("sqlite:///%s" % ruta_bd_pagos), TokenizadorCaido())
    r = _pagar(app.test_client())
    assert r.status_code == 503
    assert r.get_json() == {"error": "tokenizador_no_disponible"}
    assert _filas(ruta_bd_pagos) == 0
    assert sin_pan(logs.text)


def test_pago_inexistente(pagos):
    assert pagos.get("/pagos/pag_nada").status_code == 404
