# -*- coding: utf-8 -*-
"""Fuente central de configuracion del arnes de EXP-02.

Todo valor que dependa del entorno (endpoints, puertos, rutas, topics, modo de
ejecucion) se resuelve AQUI y en ningun otro archivo. Los modulos del arnes
importan de este, nunca leen os.environ por su cuenta ni escriben una URL a
mano. Asi el arnes se apunta a los dobles de prueba o a los servicios reales
cambiando entorno, sin tocar codigo.

Este modulo NO contiene secretos, credenciales ni material criptografico: solo
rutas a donde ese material vivira y variables que se leen del entorno. Los
valores por defecto son de desarrollo local y estan pensados para no colisionar
con los puertos que ya usa EXP-01 (3000, 5000, 8000, 9090, 15672).
"""

import os
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Modo de ejecucion
# ---------------------------------------------------------------------------
# simulado : todo contra dobles de prueba del arnes. Sirve para desarrollar.
# mixto    : parte real, parte doble. Integracion incremental.
# real     : solo servicios reales. UNICO modo que produce evidencia valida.
MODO_SIMULADO = "simulado"
MODO_MIXTO = "mixto"
MODO_REAL = "real"
MODOS_VALIDOS = (MODO_SIMULADO, MODO_MIXTO, MODO_REAL)

MODO = os.getenv("MODO", MODO_SIMULADO).strip().lower()
if MODO not in MODOS_VALIDOS:
    raise SystemExit(
        "MODO invalido: %r. Valores admitidos: %s" % (MODO, ", ".join(MODOS_VALIDOS))
    )


def evidencia_es_valida():
    """True solo si la corrida puede sustentar el experimento.

    Una corrida contra dobles demuestra que el arnes funciona, no que el
    sistema cumple. El reporte marca como NO VALIDA toda evidencia que no
    provenga de MODO=real.
    """
    return MODO == MODO_REAL


# ---------------------------------------------------------------------------
# Identidad de la corrida
# ---------------------------------------------------------------------------
# Un run_id por ejecucion: ninguna corrida sobreescribe a otra. En UTC para que
# los resultados de los cuatro integrantes sean comparables entre maquinas.
RUN_ID = os.getenv("RUN_ID") or "exp02_%s_%s" % (
    datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    MODO,
)

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
RAIZ_ARNES = Path(__file__).resolve().parent
RAIZ_EXP = RAIZ_ARNES.parent

DIR_EVIDENCIAS = Path(os.getenv("DIR_EVIDENCIAS", RAIZ_EXP / "evidencias"))
DIR_CORRIDA = DIR_EVIDENCIAS / RUN_ID

# ---------------------------------------------------------------------------
# Endpoints de los componentes bajo prueba
# ---------------------------------------------------------------------------
# Propiedad de otros integrantes. El arnes solo los consume; las rutas exactas
# se fijaran cuando se acuerden los contratos (ver README, seccion de
# dependencias). Puertos 51xx para no chocar con EXP-01.
MS_PAGOS_URL = os.getenv("MS_PAGOS_URL", "https://localhost:5101")
TOKENIZADOR_URL = os.getenv("TOKENIZADOR_URL", "https://localhost:5102")
AUDITORIA_URL = os.getenv("AUDITORIA_URL", "https://localhost:5103")

# ---------------------------------------------------------------------------
# Mensajeria asincrona (Kafka)
# ---------------------------------------------------------------------------
# Solo configuracion. El arnes todavia no habla con Kafka.
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9094")
TOPIC_EVENTOS = os.getenv("TOPIC_EVENTOS", "solventa.pagos.eventos")
TOPIC_AUDITORIA = os.getenv("TOPIC_AUDITORIA", "solventa.auditoria")

# ---------------------------------------------------------------------------
# Material criptografico: RUTAS, nunca contenido
# ---------------------------------------------------------------------------
# Los archivos los genera el script de certificados y estan en .gitignore.
# Aqui solo se declara donde buscarlos.
DIR_CERTS = Path(os.getenv("DIR_CERTS", RAIZ_EXP / "certs"))
CA_BUNDLE = Path(os.getenv("CA_BUNDLE", DIR_CERTS / "ca.crt"))
CERT_CLIENTE = Path(os.getenv("CERT_CLIENTE", DIR_CERTS / "harness.crt"))
CLAVE_CLIENTE = Path(os.getenv("CLAVE_CLIENTE", DIR_CERTS / "harness.key"))
# Par firmado por una CA distinta: material de prueba para el caso negativo de
# mTLS. Es intencionalmente invalido, no es un secreto.
CERT_NO_CONFIABLE = Path(os.getenv("CERT_NO_CONFIABLE", DIR_CERTS / "no_confiable.crt"))
CLAVE_NO_CONFIABLE = Path(os.getenv("CLAVE_NO_CONFIABLE", DIR_CERTS / "no_confiable.key"))

# ---------------------------------------------------------------------------
# Acceso de solo lectura al almacen de MS Pagos
# ---------------------------------------------------------------------------
# Necesario para verificar que el PAN no se persiste. Sin valor por defecto: la
# cadena de conexion lleva credenciales y solo puede venir del entorno.
ALMACEN_DSN = os.getenv("ALMACEN_DSN")

# ---------------------------------------------------------------------------
# Parametros de ejecucion
# ---------------------------------------------------------------------------
TIMEOUT_S = float(os.getenv("TIMEOUT_S", "10"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SERVICE_ID = os.getenv("SERVICE_ID", "harness")


def _redactar(valor):
    """Oculta un valor que pueda llevar credenciales antes de imprimirlo."""
    return "(definido)" if valor else "(no definido)"


def resumen():
    """Configuracion efectiva, apta para imprimir y para el manifest.

    Nunca incluye el contenido de ALMACEN_DSN ni de ningun archivo de claves.
    """
    return {
        "modo": MODO,
        "evidencia_valida": evidencia_es_valida(),
        "run_id": RUN_ID,
        "dir_corrida": str(DIR_CORRIDA),
        "ms_pagos_url": MS_PAGOS_URL,
        "tokenizador_url": TOKENIZADOR_URL,
        "auditoria_url": AUDITORIA_URL,
        "kafka_bootstrap": KAFKA_BOOTSTRAP,
        "topic_eventos": TOPIC_EVENTOS,
        "topic_auditoria": TOPIC_AUDITORIA,
        "dir_certs": str(DIR_CERTS),
        "almacen_dsn": _redactar(ALMACEN_DSN),
        "timeout_s": TIMEOUT_S,
    }


if __name__ == "__main__":
    # `python config.py` imprime la configuracion resuelta. Util para depurar
    # el entorno antes de correr nada.
    for clave, valor in resumen().items():
        print("%-20s %s" % (clave, valor))
    if not evidencia_es_valida():
        print("\n[!] MODO=%s: esta corrida NO produce evidencia valida "
              "para la sustentacion." % MODO)
