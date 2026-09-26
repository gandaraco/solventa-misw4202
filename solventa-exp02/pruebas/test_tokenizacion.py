import pytest

from comun import pan as pan_util
from comun.ids import nuevo_id
from conftest import PANS_SINTETICOS, sin_pan
from tokenizacion.app import crear_app


def test_devuelve_token_y_ultimos4_sin_el_pan(tokenizador):
    r = tokenizador.post("/tokens", json={"pan": "4111111111111111"})
    assert r.status_code == 201
    cuerpo = r.get_json()
    assert cuerpo["token"].startswith("tok_")
    assert cuerpo["ultimos4"] == "1111"
    assert sin_pan(r.data)


def test_misma_tarjeta_mismo_token(tokenizador):
    a = tokenizador.post("/tokens", json={"pan": "5555555555554444"})
    b = tokenizador.post("/tokens", json={"pan": "5555-5555-5555-4444"})
    c = tokenizador.post("/tokens", json={"pan": "4111111111111111"})
    assert (a.status_code, b.status_code) == (201, 200)
    assert a.get_json()["token"] == b.get_json()["token"]
    assert c.get_json()["token"] != a.get_json()["token"]


@pytest.mark.parametrize("valor", [
    "4111111111111112",       # Luhn invalido
    "123456789015",           # 12 digitos
    "41111111111111111115",   # 20 digitos
    "0000000000000000",       # trivial
    "4111x111111111111",      # caracter extrano
    4111111111111111,         # numero, no texto
    None,
])
def test_rechaza_sin_eco_del_valor(tokenizador, logs, valor):
    r = tokenizador.post("/tokens", json={"pan": valor})
    assert r.status_code == 400
    assert r.get_json() == {"error": "pan_invalido"}
    if isinstance(valor, str):
        assert valor not in logs.text


def test_boveda_no_guarda_el_pan_en_claro(tokenizador, tmp_path):
    for pan in PANS_SINTETICOS:
        assert tokenizador.post("/tokens", json={"pan": pan}).status_code == 201
    # En los bytes crudos se busca el PAN literal: el patron de 13-19 digitos
    # da falsos positivos sobre binario (cabeceras de SQLite junto a fechas).
    crudo = (tmp_path / "boveda.db").read_bytes()
    assert not any(pan.encode() in crudo for pan in PANS_SINTETICOS)


def test_logs_sin_pan(tokenizador, logs):
    for pan in PANS_SINTETICOS:
        tokenizador.post("/tokens", json={"pan": pan})
    assert "evento=tokenizado" in logs.text
    assert sin_pan(logs.text)


def test_ids_nunca_parecen_pan():
    # Si un token pareciera un PAN, el arnes lo reportaria como fuga en el
    # almacen de MS Pagos (falso positivo en C2).
    for _ in range(20000):
        assert not pan_util.PATRON_PAN.search(nuevo_id("tok"))


def test_sin_llaves_no_arranca(monkeypatch):
    for nombre in ("LLAVE_CIFRADO", "LLAVE_HMAC", "LLAVE_CIFRADO_ARCHIVO", "LLAVE_HMAC_ARCHIVO"):
        monkeypatch.delenv(nombre, raising=False)
    with pytest.raises(SystemExit):
        crear_app()
