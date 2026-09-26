# comun/pan.py
"""Reconocimiento de PAN (numero de tarjeta, ISO/IEC 7812).

La regla de candidatos es la misma que usa el detector del arnes
(harness/captura/detector_pan.py): 13 a 19 digitos con espacio o guion opcional
entre ellos. Asi, lo que el servicio considera PAN y lo que el arnes buscara en
capturas, logs y almacenes es exactamente lo mismo.

Este modulo nunca devuelve el PAN en mensajes de error: solo True/False o los
ultimos 4 digitos, que PCI-DSS permite mostrar.
"""

import re

LONGITUD_MIN = 13
LONGITUD_MAX = 19

PATRON_PAN = re.compile(r"(?<![0-9])(?:[0-9][ \-]?){12,18}[0-9](?![0-9])")
_SOLO_PAN = re.compile(r"[0-9][0-9 \-]*[0-9]")


def luhn_valido(digitos):
    if not digitos or not digitos.isdigit():
        return False
    suma = 0
    for i, c in enumerate(reversed(digitos)):
        d = ord(c) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        suma += d
    return suma % 10 == 0


def normalizar(valor):
    """Devuelve solo los digitos si `valor` tiene forma de PAN; si no, None.

    Acepta los separadores habituales (espacio y guion) para no rechazar una
    tarjeta bien digitada, pero ningun otro caracter.
    """
    if not isinstance(valor, str):
        return None
    valor = valor.strip()
    if not _SOLO_PAN.fullmatch(valor):
        return None
    digitos = valor.replace(" ", "").replace("-", "")
    if not LONGITUD_MIN <= len(digitos) <= LONGITUD_MAX:
        return None
    if len(set(digitos)) == 1:
        return None  # 0000..., relleno que pasa Luhn por casualidad
    if not luhn_valido(digitos):
        return None
    return digitos


def buscar(texto):
    """PANs validos presentes en `texto`, normalizados. Para verificar fugas."""
    hallados = []
    for m in PATRON_PAN.finditer(texto):
        digitos = normalizar(m.group(0))
        if digitos:
            hallados.append(digitos)
    return hallados
