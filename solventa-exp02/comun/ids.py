# comun/ids.py
import secrets

from comun.pan import PATRON_PAN


def nuevo_id(prefijo):
    # token_urlsafe tiene 64 simbolos, asi que una racha de 13+ digitos es
    # improbable; pero una sola bastaria para que el detector del arnes reporte
    # un "PAN" falso en un almacen o un log. Se descarta y se genera otro.
    while True:
        valor = "%s_%s" % (prefijo, secrets.token_urlsafe(18))
        if not PATRON_PAN.search(valor):
            return valor
