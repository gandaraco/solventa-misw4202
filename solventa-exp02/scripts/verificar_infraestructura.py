# scripts/verificar_infraestructura.py
"""Verificacion de infraestructura e integracion de EXP-02 contra el stack general.

Demuestra que la infraestructura sostiene las tacticas del experimento:
- Cifrar / identificar actores: mTLS con TLS 1.3 en cada servicio y en Kafka.
- Autenticar y autorizar actores: JWT del Autorizador ligado al certificado.
- Limitar la exposicion: el tokenizador y su base no son alcanzables.
- Flujo integrado: C1/C2 a traves del API Gateway y C3/C4 con los eventos
  firmados viajando por Kafka, con un atacante que altera el sobre en el canal.
- Capturas (CONF-02/03) y logs (CONF-04) sin PAN, cada una con su control positivo.

No reemplaza al arnes de Tibisay (unica evidencia oficial con MODO=real): es
la comprobacion del dueno de la infraestructura. Fases:

    python scripts/verificar_infraestructura.py              # red, gateway, kafka, flujo
    python scripts/verificar_infraestructura.py --capturas   # analiza evidencias/<RUN_ID>/capturas/*.pcap
    docker compose logs --no-color | python scripts/verificar_infraestructura.py --logs
    python scripts/verificar_infraestructura.py --resumen    # consolida las fases

Cada fase escribe evidencias/<RUN_ID>/infraestructura/<fase>.json (sin PAN) y
sale con codigo 1 si alguna verificacion falla.
"""

import base64
import json
import os
import socket
import ssl
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from comun import jws, tls  # noqa: E402
from comun import pan as pan_util  # noqa: E402

RUN_ID = os.getenv("RUN_ID") or "infra_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
DIR_CORRIDA = Path(os.getenv("DIR_EVIDENCIAS", RAIZ / "evidencias")) / RUN_ID
CERTS = Path(os.getenv("DIR_CERTS", RAIZ / "certs"))
SECRETOS = Path(os.getenv("DIR_SECRETOS", RAIZ / "secretos"))
CA = str(CERTS / "ca.crt")
PROPIO = (str(CERTS / "harness.crt"), str(CERTS / "harness.key"))
ATACANTE = (str(CERTS / "atacante.crt"), str(CERTS / "atacante.key"))
AJENO = (str(CERTS / "no_confiable.crt"), str(CERTS / "no_confiable.key"))

GATEWAY = os.getenv("GATEWAY_URL", "https://api-gateway:8443")
AUTORIZADOR = os.getenv("AUTORIZADOR_URL", "https://autorizador:8443")
AUDITORIA = os.getenv("AUDITORIA_URL", "https://auditoria:8443")
KAFKA = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TOPICO = os.getenv("TOPICO_CONSENTIMIENTOS", "solventa.consentimiento.eventos")
DSN = os.getenv("ALMACEN_DSN", "postgresql://harness_lectura:harness_lectura_dev@bd-pagos/pagos")

# Servicios con mTLS: (nombre, host, puerto).
SERVICIOS_HTTPS = [
    ("api-gateway", "api-gateway", 8443), ("autorizador", "autorizador", 8443),
    ("ms-pagos", "ms-pagos", 8443), ("ms-consentimiento", "ms-consentimiento", 8443),
    ("ms-suscripcion", "ms-suscripcion", 8443), ("auditoria", "auditoria", 8443),
]
# Deben ser INALCANZABLES desde red-borde / red-datos-pagos (alcance PCI).
AISLADOS = [("tokenizador", 8443), ("bd-tokenizacion", 5432)]

# Valores publicos de prueba de las pasarelas (harness/fixtures/pans_sinteticos.json).
PANS = ["4111111111111111", "4012888888881881", "5555555555554444", "378282246310005",
        "6011111111111117", "30569309025904", "4222222222222", "4111111111111111110"]
# Solo para los controles positivos de captura y logs: nunca entra al flujo de pago.
PAN_CONTROL = "4000056655665556"

SCOPES = "pagos:escribir pagos:leer consentimientos:escribir suscripciones:leer"
resultados = []


# --- Utilidades --------------------------------------------------------------

def verificar(id_caso, descripcion, ok, detalle=""):
    resultados.append({"id": id_caso, "verificacion": descripcion,
                       "resultado": "PASS" if ok else "FAIL", "detalle": str(detalle)})
    print("%-4s %-28s %s %s" % ("PASS" if ok else "FAIL", id_caso, descripcion, detalle))
    return ok


def sin_pan(texto, pans=PANS):
    return not pan_util.buscar(texto) and not any(p in texto for p in pans)


def sesion(cert=PROPIO):
    s = requests.Session()
    s.cert = cert
    s.verify = CA
    return s


def esperar(condicion, timeout_s=30, paso_s=0.5):
    limite = time.monotonic() + timeout_s
    while True:
        try:
            valor = condicion()
            if valor:
                return valor
        except (requests.RequestException, ValueError, KeyError):
            pass
        if time.monotonic() > limite:
            return None
        time.sleep(paso_s)


def handshake_rechazado(host, puerto, cert=None, tls_max=None):
    """True si el servidor no deja establecer un canal usable.

    En TLS 1.3 el servidor valida el certificado del cliente despues del
    Finished del cliente: el rechazo llega como alerta en la primera lectura.
    Si el canal queda abierto (la lectura agota el tiempo), fue aceptado. Un
    puerto que ni siquiera acepta TCP no demuestra un rechazo: cuenta como falla.
    """
    ctx = ssl.create_default_context(cafile=CA)
    if cert:
        ctx.load_cert_chain(*cert)
    if tls_max:
        ctx.maximum_version = tls_max
    try:
        s = socket.create_connection((host, puerto), timeout=5)
    except OSError:
        return False
    try:
        with ctx.wrap_socket(s, server_hostname=host) as t:
            t.settimeout(4)
            return t.recv(1) == b""
    except TimeoutError:
        return False
    except (ssl.SSLError, ConnectionError):
        return True
    finally:
        s.close()


def texto_claro_rechazado(host, puerto):
    """True si el puerto acepta TCP pero no atiende HTTP sin TLS."""
    try:
        s = socket.create_connection((host, puerto), timeout=5)
    except OSError:
        return False
    try:
        s.settimeout(4)
        s.sendall(b"GET /salud HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % host.encode())
        return not s.recv(64).startswith(b"HTTP/1.1 200")
    except OSError:  # incluye el corte de la conexion y el tiempo agotado
        return True
    finally:
        s.close()


def config_kafka(cert=PROPIO):
    return {"bootstrap.servers": KAFKA, "security.protocol": "SSL",
            "ssl.ca.location": CA, "ssl.certificate.location": cert[0],
            "ssl.key.location": cert[1], "ssl.endpoint.identification.algorithm": "https",
            "client.id": "verificador"}


def token(cert=PROPIO, scope=SCOPES):
    r = sesion(cert).post(AUTORIZADOR + "/oauth/token", timeout=10,
                          data={"grant_type": "client_credentials", "scope": scope})
    return r.status_code, (r.json().get("access_token") if r.ok else r.json().get("error"))


def gateway(metodo, ruta, token_acceso=None, cert=PROPIO, marcador=None, **kwargs):
    cabeceras = {}
    if token_acceso:
        cabeceras["Authorization"] = "Bearer " + token_acceso
    if marcador:
        cabeceras["X-Marcador"] = marcador
    return sesion(cert).request(metodo, GATEWAY + ruta, headers=cabeceras, timeout=15, **kwargs)


def auditoria(marcador):
    return sesion().get(AUDITORIA + "/registros", params={"marcador": marcador}, timeout=10).json()


def _b64(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def guardar(fase, extra=None):
    destino = DIR_CORRIDA / "infraestructura"
    destino.mkdir(parents=True, exist_ok=True)
    documento = {"run_id": RUN_ID, "fase": fase,
                 "fecha": datetime.now(timezone.utc).isoformat(),
                 "resumen": {"pass": sum(r["resultado"] == "PASS" for r in resultados),
                             "total": len(resultados)},
                 "verificaciones": resultados}
    if extra:
        documento.update(extra)
    texto = json.dumps(documento, indent=2, ensure_ascii=False)
    # La evidencia tampoco puede contener un PAN.
    assert not any(p in texto for p in PANS + [PAN_CONTROL]), "la evidencia contiene un PAN"
    (destino / (fase + ".json")).write_text(texto, encoding="utf-8")
    print("\nEvidencia: %s" % (destino / (fase + ".json")).relative_to(RAIZ))


# --- Fase de red ---------------------------------------------------------------

def esperar_stack():
    for nombre, host, puerto in SERVICIOS_HTTPS:
        ok = esperar(lambda: sesion().get("https://%s:%d/salud" % (host, puerto),
                                          timeout=3).status_code == 200, timeout_s=120, paso_s=2)
        if not ok:
            raise SystemExit("%s no responde; revisar `docker compose ps`" % nombre)


def fase_mtls():
    print("\n== mTLS con TLS 1.3 en cada servicio (MTLS-01..03) ==")
    for nombre, host, puerto in SERVICIOS_HTTPS:
        verificar("MTLS-01/" + nombre, "sin certificado de cliente: rechazado",
                  handshake_rechazado(host, puerto))
        verificar("MTLS-02/" + nombre, "certificado de otra CA: rechazado",
                  handshake_rechazado(host, puerto, AJENO))
        verificar("MTLS-TLS12/" + nombre, "TLS 1.2: rechazado",
                  handshake_rechazado(host, puerto, PROPIO, ssl.TLSVersion.TLSv1_2))
        verificar("MTLS-CLARO/" + nombre, "HTTP sin TLS: no atendido",
                  texto_claro_rechazado(host, puerto))
        r = sesion().get("https://%s:%d/salud" % (host, puerto), timeout=5)
        verificar("MTLS-03/" + nombre, "certificado legitimo: atendido (control)",
                  r.status_code == 200, "HTTP %d" % r.status_code)

    print("\n== Kafka: listener SSL, TLS 1.3 y certificado obligatorio ==")
    host, puerto = KAFKA.split(":")
    verificar("KAFKA-MTLS-01", "Kafka sin certificado: rechazado", handshake_rechazado(host, int(puerto)))
    verificar("KAFKA-MTLS-02", "Kafka con certificado de otra CA: rechazado",
              handshake_rechazado(host, int(puerto), AJENO))
    verificar("KAFKA-TLS12", "Kafka con TLS 1.2: rechazado",
              handshake_rechazado(host, int(puerto), PROPIO, ssl.TLSVersion.TLSv1_2))
    from confluent_kafka.admin import AdminClient
    try:
        topicos = AdminClient(config_kafka()).list_topics(timeout=10).topics
        verificar("KAFKA-MTLS-03", "Kafka con certificado legitimo: metadatos (control)",
                  TOPICO in topicos, "topico %s presente" % TOPICO)
    except Exception as exc:  # noqa: BLE001
        verificar("KAFKA-MTLS-03", "Kafka con certificado legitimo: metadatos (control)",
                  False, type(exc).__name__)


def fase_aislamiento():
    print("\n== Limitar la exposicion: alcance PCI aislado ==")
    for host, puerto in AISLADOS:
        try:
            socket.create_connection((host, puerto), timeout=3).close()
            alcanzable = True
        except OSError:
            alcanzable = False
        verificar("AISL/" + host, "no alcanzable desde red-borde ni red-datos-pagos",
                  not alcanzable, "%s:%d" % (host, puerto))


def fase_gateway():
    print("\n== API Gateway: JWT del Autorizador ligado al certificado ==")
    corrida = RUN_ID[-8:].upper()
    codigo, legitimo = token()
    verificar("JWT-00", "harness obtiene token (client credentials + mTLS)",
              codigo == 200 and bool(legitimo), "HTTP %d" % codigo)

    marcador = "INFRA-%s-JWT-01" % corrida
    r = gateway("POST", "/pagos", marcador=marcador, json={"pan": PANS[0], "monto": 1, "concepto": "prima"})
    verificar("JWT-01", "sin token: 401", r.status_code == 401, r.text.strip())

    huella = tls.huella_certificado(ssl.PEM_cert_to_DER_cert(Path(PROPIO[0]).read_text()))
    ahora = int(time.time())
    claims = {"iss": "solventa-autorizador", "sub": "harness", "aud": "solventa-api-gateway",
              "iat": ahora, "nbf": ahora, "exp": ahora + 300, "scope": SCOPES,
              "cnf": {"x5t#S256": huella}}
    falso = jws.firmar(claims, (SECRETOS / "no_confiable_jws.key").read_bytes(),
                           "autorizador-v1", typ="JWT")
    r = gateway("POST", "/pagos", falso, json={"pan": PANS[0], "monto": 1, "concepto": "prima"})
    verificar("JWT-02", "token firmado con otra llave: 401", r.status_code == 401, r.text.strip())

    cabecera = _b64(json.dumps({"alg": "none", "kid": "autorizador-v1", "typ": "JWT"}).encode())
    sin_firma = cabecera + "." + _b64(json.dumps(claims).encode()) + ".x"
    r = gateway("GET", "/pagos?referencia=x", sin_firma)
    verificar("JWT-03", "alg=none: 401", r.status_code == 401, r.text.strip())

    r = gateway("GET", "/pagos?referencia=x", legitimo, cert=ATACANTE)
    verificar("JWT-04", "token robado usado con otro certificado valido: 401",
              r.status_code == 401, r.text.strip())

    codigo, error = token(ATACANTE)
    verificar("JWT-05", "certificado valido no registrado no obtiene token: 401",
              codigo == 401, error)

    _, solo_lectura = token(scope="pagos:leer")
    r = gateway("POST", "/pagos", solo_lectura, json={"pan": PANS[0], "monto": 1, "concepto": "prima"})
    verificar("JWT-06", "scope insuficiente: 403", r.status_code == 403, r.text.strip())

    r = gateway("POST", "/tokens", legitimo, json={"pan": PANS[0]})
    verificar("GW-01", "el tokenizador no es enrutable desde el gateway: 404",
              r.status_code == 404, r.text.strip())
    r = gateway("GET", "/pagos/" + PANS[1], legitimo)
    verificar("GW-02", "id con forma de PAN en la ruta no se reenvia: 404",
              r.status_code == 404, r.text.strip())

    registros = esperar(lambda: auditoria(marcador), timeout_s=15)
    verificar("AUD-GW", "rechazo del gateway registrado en Auditoria",
              bool(registros) and registros[0]["accion"] == "ACCESO_RECHAZADO"
              and registros[0]["motivo"] == "token_ausente",
              "%d registro(s)" % len(registros or []))
    return legitimo


def fase_pagos(token_acceso):
    print("\n== Flujo de pago por el gateway: C1 (respuestas) y C2 (almacen) ==")
    corrida = "INFRA-%s-PAGO" % RUN_ID[-8:].upper()
    respuestas = [gateway("POST", "/pagos", token_acceso, json={
        "pan": pan, "monto": 1000 + i, "concepto": "prima", "referencia": "%s-%d" % (corrida, i)})
        for i, pan in enumerate(PANS)]
    creados = sum(r.status_code == 201 for r in respuestas)
    verificar("FLUJO-01", "pagos por gateway -> ms-pagos -> tokenizador", creados == len(PANS),
              "%d/%d con 201" % (creados, len(PANS)))
    cuerpos = "\n".join(r.text for r in respuestas)
    verificar("CONF-01", "respuestas del gateway sin PAN", sin_pan(cuerpos))
    verificar("CONF-01b", "respuestas con token tok_...",
              all(r.json().get("tokenTarjeta", "").startswith("tok_") for r in respuestas if r.ok))

    # Un PAN en la query string viaja cifrado y no debe quedar en ningun log (CONF-04).
    r = gateway("GET", "/pagos", token_acceso, params={"referencia": corrida + "-0", "pan": PANS[2]})
    verificar("FLUJO-02", "consulta por referencia a traves del gateway",
              r.status_code == 200 and len(r.json()) == 1, "HTTP %d" % r.status_code)

    with psycopg.connect(DSN) as cx:
        filas = cx.execute("SELECT * FROM pagos WHERE referencia LIKE %s", (corrida + "-%",)).fetchall()
        todo = cx.execute("SELECT * FROM pagos").fetchall()
    texto = json.dumps([list(map(str, f)) for f in todo])
    verificar("PERS-03", "control: las filas de la corrida estan en el almacen",
              len(filas) == len(PANS), "%d filas" % len(filas))
    verificar("PERS-01", "almacen de MS Pagos sin PAN", sin_pan(texto), "%d filas revisadas" % len(todo))
    verificar("PERS-02", "cada fila guarda el token",
              all(str(f[1]).startswith("tok_") for f in filas))

    registros = esperar(lambda: auditoria(corrida + "-0"), timeout_s=10)
    verificar("AUD-PAGO", "ms-pagos registra PAGO_REGISTRADO en Auditoria por mTLS",
              bool(registros) and registros[0]["accion"] == "PAGO_REGISTRADO",
              "%d registro(s)" % len(registros or []))


def _leer_sobre(event_id, timeout_s=20):
    """El atacante en el canal: lee del topico el sobre legitimo publicado."""
    from confluent_kafka import Consumer
    consumidor = Consumer(dict(config_kafka(), **{
        "group.id": "verificador-" + uuid.uuid4().hex[:8],
        "auto.offset.reset": "earliest", "enable.auto.commit": False}))
    consumidor.subscribe([TOPICO])
    limite = time.monotonic() + timeout_s
    try:
        while time.monotonic() < limite:
            mensaje = consumidor.poll(1.0)
            if mensaje is None or mensaje.error():
                continue
            sobre = json.loads(mensaje.value())
            if sobre.get("eventId") == event_id:
                return sobre
    finally:
        consumidor.close()
    return None


def _publicar(sobre):
    from confluent_kafka import Producer
    productor = Producer(config_kafka())
    productor.produce(TOPICO, value=json.dumps(sobre).encode("utf-8"))
    return productor.flush(10) == 0


def _alterar(jws_compacto, campo_nuevo):
    cabecera, cuerpo, firma = jws_compacto.split(".")
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    datos["datos"]["suscripcionId"] = campo_nuevo
    return cabecera + "." + _b64(json.dumps(datos, sort_keys=True, separators=(",", ":")).encode()) + "." + firma


def fase_kafka(token_acceso):
    print("\n== Integridad sobre Kafka: C3 (valido) y C4 (alterado en el canal) ==")
    base = "INFRA-%s" % RUN_ID[-8:].upper()
    sus = "sus-infra-" + uuid.uuid4().hex[:8]

    def estado(sid):
        return gateway("GET", "/suscripciones/" + sid, token_acceso).json()

    antes = estado(sus)
    r = gateway("POST", "/consentimientos", token_acceso, json={
        "suscripcionId": sus, "actorId": "cliente-infra", "marcador": base + "-KAFKA-VALIDO"})
    cuerpo = r.json()
    publicado = r.status_code == 201 and cuerpo.get("publicado") and \
        cuerpo.get("resultado", {}).get("topico") == TOPICO
    verificar("KAFKA-01", "consentimiento firmado publicado en Kafka (acks=all)", publicado,
              "offset %s" % cuerpo.get("resultado", {}).get("offset"))
    despues = esperar(lambda: estado(sus)["estado"] == "ACTIVA" and estado(sus), timeout_s=20)
    verificar("INTEG-01/kafka", "evento valido consumido: PENDIENTE -> ACTIVA",
              antes["estado"] == "PENDIENTE" and bool(despues))
    registros = esperar(lambda: auditoria(base + "-KAFKA-VALIDO"), timeout_s=10)
    verificar("INTEG-01/auditoria", "Auditoria registra ACEPTADO",
              bool(registros) and registros[0]["resultado"] == "ACEPTADO")

    legitimo = _leer_sobre(cuerpo.get("eventId"))
    verificar("KAFKA-02", "atacante con certificado valido lee el sobre del topico", bool(legitimo))
    if not legitimo:
        return

    objetivo = sus + "-alterada"
    antes_objetivo = estado(objetivo)
    alterado = {"eventId": legitimo["eventId"], "marcador": base + "-KAFKA-ALTERADO",
                "jws": _alterar(legitimo["jws"], objetivo)}
    verificar("KAFKA-03", "sobre alterado reinyectado en el topico", _publicar(alterado))
    registros = esperar(lambda: auditoria(base + "-KAFKA-ALTERADO"), timeout_s=20)
    verificar("INTEG-02/kafka", "alteracion del payload rechazada (firma_invalida) y auditada",
              bool(registros) and registros[0]["resultado"] == "RECHAZADO"
              and registros[0]["motivo"] == "firma_invalida")
    verificar("INTEG-02/estado", "estado del objetivo sin cambios (antes == despues)",
              estado(objetivo) == antes_objetivo, antes_objetivo["estado"])
    verificar("INTEG-02/original", "la suscripcion legitima conserva su ultimo evento",
              estado(sus)["ultimoEventoId"] == legitimo["eventId"])

    sin_firma = {"eventId": "evt-infra-sin-firma-" + uuid.uuid4().hex[:6],
                 "marcador": base + "-KAFKA-SIN-FIRMA"}
    _publicar(sin_firma)
    registros = esperar(lambda: auditoria(base + "-KAFKA-SIN-FIRMA"), timeout_s=20)
    verificar("INTEG-04/kafka", "sobre sin firma rechazado (firma_ausente) y auditado",
              bool(registros) and registros[0]["motivo"] == "firma_ausente")


def controles_captura():
    """Control positivo de las capturas: un PAN de control en claro por UDP.

    Si el analisis de la captura no lo encuentra, un "0 PAN" no demostraria nada.
    Va al puerto 9 (discard): nadie lo procesa ni lo registra en logs.
    """
    mensaje = ("control-captura %s %s" % (RUN_ID, PAN_CONTROL)).encode("ascii")
    for host in ("api-gateway", "ms-pagos", "kafka"):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _ in range(3):
                s.sendto(mensaje, (host, 9))
    print("\nControl de captura enviado (UDP/9) a api-gateway, ms-pagos y kafka")


def fase_red():
    esperar_stack()
    controles_captura()
    fase_mtls()
    fase_aislamiento()
    token_acceso = fase_gateway()
    fase_pagos(token_acceso)
    fase_kafka(token_acceso)
    controles_captura()
    guardar("red")


# --- Fase de capturas ------------------------------------------------------------

SEGMENTOS = {8443: "https-mtls", 9092: "kafka-tls", 5432: "postgres-post-tokenizacion",
             9: "control-udp"}


def _paquetes(ruta):
    """(puerto_servidor, carga) de cada paquete IPv4 TCP/UDP de un pcap de tcpdump -i any."""
    datos = Path(ruta).read_bytes()
    if len(datos) < 24:
        return
    endian = "<" if datos[:4] == b"\xd4\xc3\xb2\xa1" else ">"
    tipo_enlace = struct.unpack(endian + "I", datos[20:24])[0]
    pos = 24
    while pos + 16 <= len(datos):
        _, _, incl, _ = struct.unpack(endian + "IIII", datos[pos:pos + 16])
        trama = datos[pos + 16:pos + 16 + incl]
        pos += 16 + incl
        if tipo_enlace == 276:      # LINUX_SLL2
            protocolo, ip = struct.unpack(">H", trama[0:2])[0], trama[20:]
        elif tipo_enlace == 113:    # LINUX_SLL
            protocolo, ip = struct.unpack(">H", trama[14:16])[0], trama[16:]
        else:
            continue
        if protocolo != 0x0800 or len(ip) < 20:
            continue
        ihl, proto = (ip[0] & 0x0F) * 4, ip[9]
        l4 = ip[ihl:]
        if proto == 6 and len(l4) >= 20:
            origen, destino = struct.unpack(">HH", l4[:4])
            carga = l4[(l4[12] >> 4) * 4:]
        elif proto == 17 and len(l4) >= 8:
            origen, destino = struct.unpack(">HH", l4[:4])
            carga = l4[8:]
        else:
            continue
        puerto = destino if destino in SEGMENTOS else origen
        yield puerto, carga


def fase_capturas():
    print("\n== Capturas de trafico: CONF-02 (post-tokenizacion) y CONF-03 (mTLS) ==")
    capturas = sorted((DIR_CORRIDA / "capturas").glob("*.pcap"))
    verificar("CAP-00", "capturas presentes", len(capturas) == 3, ", ".join(c.name for c in capturas))
    detalle = {}
    for ruta in capturas:
        crudo = ruta.read_bytes()
        segmentos = {}
        for puerto, carga in _paquetes(ruta):
            nombre = SEGMENTOS.get(puerto, "otro")
            seg = segmentos.setdefault(nombre, {"paquetes": 0, "bytes_carga": 0,
                                                "pan_encontrados": 0, "tokens_visibles": 0})
            seg["paquetes"] += 1
            seg["bytes_carga"] += len(carga)
            seg["pan_encontrados"] += sum(p.encode() in carga for p in PANS)
            seg["tokens_visibles"] += carga.count(b"tok_")
        detalle[ruta.name] = {"bytes": len(crudo), "segmentos": segmentos}
        nombre = ruta.stem
        # Bytes crudos: se busca el PAN literal (el patron da falsos positivos en binario).
        verificar("CAP-CONTROL/" + nombre, "control: la captura SI ve un PAN enviado en claro",
                  PAN_CONTROL.encode() in crudo)
        cifrados = {k: v for k, v in segmentos.items() if k in ("https-mtls", "kafka-tls")}
        verificar("CONF-03/" + nombre, "segmentos mTLS sin PAN en claro",
                  bool(cifrados) and all(v["pan_encontrados"] == 0 for v in cifrados.values()),
                  ", ".join("%s: %d paquetes" % (k, v["paquetes"]) for k, v in cifrados.items()))
        verificar("CONF-02/" + nombre, "captura completa sin ningun PAN del flujo",
                  not any(p.encode() in crudo for p in PANS), "%d bytes" % len(crudo))
    if "ms-pagos.pcap" in detalle:
        pg = detalle["ms-pagos.pcap"]["segmentos"].get("postgres-post-tokenizacion", {})
        # Este segmento va en claro: ver los tokens es el control de que "0 PAN"
        # se debe a la tokenizacion y no al cifrado.
        verificar("CONF-02/postgres", "segmento ms-pagos -> bd-pagos (sin TLS) solo lleva tokens",
                  pg.get("tokens_visibles", 0) > 0 and pg.get("pan_encontrados", 1) == 0,
                  "%d paquetes, %d tokens en claro" % (pg.get("paquetes", 0), pg.get("tokens_visibles", 0)))
    guardar("capturas", {"capturas": detalle})


# --- Fase de logs ----------------------------------------------------------------

def fase_logs():
    print("\n== Logs de todos los contenedores: CONF-04 ==")
    texto = sys.stdin.read()
    lineas = texto.splitlines()
    servicios = sorted({l.split("|", 1)[0].strip() for l in lineas if "|" in l})
    verificar("LOG-CONTROL", "control: se leyeron los logs del flujo",
              "evento=pago_registrado" in texto and "evento=jws_rechazado" in texto
              and "evento=acceso_rechazado" in texto, "%d lineas, %d contenedores" % (len(lineas), len(servicios)))
    verificar("CONF-04", "ningun PAN literal en los logs", not any(p in texto for p in PANS),
              "incluye un ?pan= y un PAN en la ruta enviados a proposito")
    # El patron de PAN se aplica a los servicios Python; Kafka y Postgres
    # imprimen marcas de tiempo de 13 digitos que pasarian Luhn por azar.
    propios = "\n".join(l for l in lineas if not l.startswith(("kafka", "bd-")))
    verificar("CONF-04b", "ningun candidato a PAN (patron + Luhn) en logs de servicios Python",
              not pan_util.buscar(propios))
    guardar("logs", {"contenedores": servicios})


# --- Resumen ---------------------------------------------------------------------

def fase_resumen():
    fases = {}
    for ruta in sorted((DIR_CORRIDA / "infraestructura").glob("*.json")):
        if ruta.stem != "resumen":
            fases[ruta.stem] = json.loads(ruta.read_text(encoding="utf-8"))
    total = sum(f["resumen"]["total"] for f in fases.values())
    aprobadas = sum(f["resumen"]["pass"] for f in fases.values())
    fallas = [v for f in fases.values() for v in f["verificaciones"] if v["resultado"] == "FAIL"]
    resumen = {"run_id": RUN_ID, "fases": {k: v["resumen"] for k, v in fases.items()},
               "pass": aprobadas, "total": total, "fallas": fallas}
    destino = DIR_CORRIDA / "infraestructura" / "resumen.json"
    destino.write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    for nombre, r in resumen["fases"].items():
        print("%-10s %d/%d PASS" % (nombre, r["pass"], r["total"]))
    print("TOTAL      %d/%d PASS  (%s)" % (aprobadas, total, RUN_ID))
    faltantes = {"red", "capturas", "logs"} - set(fases)
    if faltantes:
        print("Fases sin ejecutar: %s" % ", ".join(sorted(faltantes)))
    return 1 if fallas or faltantes else 0


if __name__ == "__main__":
    if "--resumen" in sys.argv:
        sys.exit(fase_resumen())
    {"--capturas": fase_capturas, "--logs": fase_logs}.get(
        next((a for a in sys.argv[1:] if a.startswith("--")), ""), fase_red)()
    fallidas = [r for r in resultados if r["resultado"] == "FAIL"]
    print("%d/%d PASS" % (len(resultados) - len(fallidas), len(resultados)))
    sys.exit(1 if fallidas else 0)
