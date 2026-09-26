# comun/registro.py
import logging
import os
import sys


def configurar(servicio):
    # Mismo formato clave=valor que EXP-01, para que el arnes lea los logs igual.
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger(os.getenv("SERVICE_ID", servicio))
