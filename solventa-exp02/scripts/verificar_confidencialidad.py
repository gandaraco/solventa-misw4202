# scripts/verificar_confidencialidad.py
"""Verificacion de extremo a extremo del tramo de confidencialidad, contra el stack levantado.

No reemplaza al arnes de Tibisay (que produce la evidencia oficial del
experimento): es la comprobacion del dueno del componente antes de integrar.

    docker compose -f docker-compose.pagos.yml up -d --build
    docker compose -f docker-compose.pagos.yml run --rm verificacion
    docker compose -f docker-compose.pagos.yml logs --no-color \
        | docker compose -f docker-compose.pagos.yml run --rm -T verificacion python scripts/verificar_confidencialidad.py --logs

Sale con codigo 1 si alguna verificacion falla.
"""

import json
import os
import socket
import ssl
import sys
import uuid

import psycopg
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comun import pan as pan_util  # noqa: E402

URL = os.getenv("MS_PAGOS_URL", "https://ms-pagos:8443")
DSN = os.getenv("ALMACEN_DSN", "postgresql://harness_lectura:harness_lectura_dev@bd-pagos/pagos")
CERTS = os.getenv("DIR_CERTS", "certs")
CA = os.path.join(CERTS, "ca.crt")
PROPIO = (os.path.join(CERTS, "harness.crt"), os.path.join(CERTS, "harness.key"))
AJENO = (os.path.join(CERTS, "no_confiable.crt"), os.path.join(CERTS, "no_confiable.key"))

# Valores publicos de prueba de las pasarelas (harness/fixtures/pans_sinteticos.json).
PANS = ["4111111111111111", "4012888888881881", "5555555555554444", "378282246310005",
        "6011111111111117", "30569309025904", "4222222222222", "4111111111111111110"]

resultados = []


def verificar(nombre, ok, detalle=""):
    resultados.append({"verificacion": nombre, "resultado": "PASS" if ok else "FAIL", "detalle": detalle})
    print("%-4s %s %s" % ("PASS" if ok else "FAIL", nombre, detalle))


def rechazada(**kwargs):
    try:
        requests.get(URL + "/salud", timeout=5, **kwargs)
        return False
    except requests.exceptions.SSLError:
        return True
    except requests.exceptions.ConnectionError:
        return True  # TLS 1.3 reporta el rechazo del certificado al leer, como conexion cortada


def red_y_almacen():
    corrida = "VERIF-" + uuid.uuid4().hex[:8].upper()

    # 1. Flujo PAN -> token con mTLS valido.
    respuestas = []
    for i, pan in enumerate(PANS):
        r = requests.post(URL + "/pagos", cert=PROPIO, verify=CA, timeout=10, json={
            "pan": pan, "monto": 1000 + i, "concepto": "prima", "referencia": "%s-%d" % (corrida, i)})
        respuestas.append(r)
    ok = all(r.status_code == 201 for r in respuestas)
    verificar("pagos_registrados", ok, "%d/%d con 201" % (sum(r.status_code == 201 for r in respuestas), len(PANS)))
    cuerpos = "\n".join(r.text for r in respuestas)
    verificar("respuestas_sin_pan", not pan_util.buscar(cuerpos) and not any(p in cuerpos for p in PANS))
    verificar("respuestas_con_token", all(r.json().get("tokenTarjeta", "").startswith("tok_") for r in respuestas if r.ok))

    # 2. Canal: solo clientes con certificado de la CA del experimento y TLS 1.3.
    verificar("mtls_sin_certificado_rechazado", rechazada(verify=CA))
    verificar("mtls_otra_ca_rechazado", rechazada(verify=CA, cert=AJENO))
    ctx = ssl.create_default_context(cafile=CA)
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(*PROPIO)
    host, puerto = URL.removeprefix("https://").split(":")
    try:
        with socket.create_connection((host, int(puerto)), timeout=5) as s:
            ctx.wrap_socket(s, server_hostname=host).close()
        verificar("tls12_rechazado", False)
    except ssl.SSLError:
        verificar("tls12_rechazado", True)
    try:
        socket.create_connection(("tokenizador", 8443), timeout=3).close()
        verificar("tokenizador_aislado", False, "alcanzable desde red-borde")
    except OSError:
        verificar("tokenizador_aislado", True, "no alcanzable desde red-borde")

    # 3. Almacen (criterio C2), con el usuario de solo lectura del arnes.
    with psycopg.connect(DSN) as cx:
        filas = cx.execute("SELECT * FROM pagos WHERE referencia LIKE %s", (corrida + "-%",)).fetchall()
        todo = cx.execute("SELECT * FROM pagos").fetchall()
        columnas = [d.name for d in cx.execute("SELECT * FROM pagos LIMIT 0").description]
    verificar("control_filas_persistidas", len(filas) == len(PANS), "%d filas de esta corrida" % len(filas))
    texto = json.dumps([list(map(str, f)) for f in todo])
    verificar("almacen_sin_pan", not pan_util.buscar(texto) and not any(p in texto for p in PANS),
              "%d filas revisadas" % len(todo))
    verificar("almacen_sin_columna_pan", not any("pan" == c or "tarjeta" == c for c in columnas), ",".join(columnas))
    try:
        with psycopg.connect(DSN) as cx:
            cx.execute("DELETE FROM pagos")
        verificar("usuario_arnes_solo_lectura", False)
    except psycopg.errors.InsufficientPrivilege:
        verificar("usuario_arnes_solo_lectura", True)


def logs():
    texto = sys.stdin.read()
    lineas = texto.count("\n")
    verificar("control_logs_leidos", "evento=pago_registrado" in texto, "%d lineas" % lineas)
    verificar("logs_sin_pan", not pan_util.buscar(texto) and not any(p in texto for p in PANS))


if __name__ == "__main__":
    logs() if "--logs" in sys.argv else red_y_almacen()
    fallas = [r for r in resultados if r["resultado"] == "FAIL"]
    print("\n%d/%d PASS" % (len(resultados) - len(fallas), len(resultados)))
    sys.exit(1 if fallas else 0)
