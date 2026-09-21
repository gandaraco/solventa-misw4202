# -*- coding: utf-8 -*-
"""Detector de PAN en texto y archivos locales.

Es la pieza de la que depende la credibilidad de los criterios 1 y 2 de EXP-02
("sin PAN en texto claro", "0 persistencias del PAN"). Un detector roto hace
pasar esos criterios trivialmente: si nunca encuentra nada, todo parece limpio.
Por eso su comportamiento se demuestra con el control positivo CONF-99 antes de
aceptar cualquier resultado de cero hallazgos.

Sesgo de diseno: en un detector de fugas, un FALSO NEGATIVO (no ver un PAN que
si esta) es mucho peor que un falso positivo (revisar de mas). Ante la duda, el
detector reporta. Los filtros opcionales que reducen ruido vienen desactivados.

REGLA INVIOLABLE: este modulo nunca devuelve, imprime ni escribe el PAN
completo. Un hallazgo se describe con posicion, longitud, huella SHA-256 y, si
se pide explicitamente, una version enmascarada que solo deja los ultimos 4
digitos.

Advertencia sobre la huella: el espacio de tarjetas es pequeno, asi que un
SHA-256 de un PAN es reversible por fuerza bruta. La huella sirve para
correlacionar el mismo valor entre artefactos, no para proteger el dato: el
artefacto que la contiene se sigue tratando como sensible.

Solo biblioteca estandar: el detector debe poder probarse sin entorno, sin
contenedores y sin ningun componente de los demas integrantes.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

# Un PAN tiene entre 13 y 19 digitos (ISO/IEC 7812).
LONGITUD_MIN = 13
LONGITUD_MAX = 19

SEPARADORES = " -"

# Candidatos: 13 a 19 digitos, con un separador opcional (espacio o guion)
# entre digitos.
#
#   (?<![0-9])            no empezar en mitad de un numero mas largo
#   (?:[0-9][ \-]?){12,18} 12 a 18 digitos, cada uno con separador opcional
#   [0-9]                 el digito final, que cierra sin separador
#   (?![0-9])             no terminar en mitad de un numero mas largo
#
# Las dos guardas hacen que una cadena de 20 digitos no produzca un falso
# candidato de 19 recortando un extremo.
_PATRON = re.compile(r"(?<![0-9])(?:[0-9][ \-]?){12,18}[0-9](?![0-9])")

# Los archivos se leen por bloques para poder inspeccionar capturas grandes sin
# cargarlas completas en memoria. El solape evita partir un candidato justo en
# la frontera: 19 digitos mas 18 separadores caben de sobra en 64 caracteres.
TAM_BLOQUE = 1 << 20  # 1 MiB
SOLAPE = 64


def normalizar(candidato):
    """Deja solo los digitos del candidato."""
    return "".join(c for c in candidato if c.isdigit())


def luhn_valido(digitos):
    """Algoritmo de Luhn (ISO/IEC 7812-1) sobre una cadena de digitos.

    Se recorre de derecha a izquierda duplicando uno de cada dos digitos; si al
    duplicar se pasa de 9 se le restan 9. El numero es valido si la suma total
    es multiplo de 10.
    """
    if not digitos or not digitos.isdigit():
        return False
    suma = 0
    duplicar = False
    for c in reversed(digitos):
        d = ord(c) - 48
        if duplicar:
            d *= 2
            if d > 9:
                d -= 9
        suma += d
        duplicar = not duplicar
    return suma % 10 == 0


def huella(digitos):
    """SHA-256 del valor normalizado. Identifica el valor sin exponerlo."""
    return hashlib.sha256(digitos.encode("ascii")).hexdigest()


def enmascarar(digitos):
    """Version enmascarada: solo los ultimos 4 digitos quedan visibles."""
    return "*" * (len(digitos) - 4) + digitos[-4:]


def _es_trivial(digitos):
    """True si todos los digitos son iguales (0000..., 1111...).

    Esas cadenas pasan Luhn por casualidad y abundan como relleno en capturas
    binarias y volcados de memoria. Ningun BIN real las produce.
    """
    return len(set(digitos)) == 1


def _agrupacion_plausible(texto):
    """True si los separadores forman una agrupacion tipica de tarjeta.

    Filtro OPCIONAL y desactivado por defecto. Descarta casos como
    "id=123456789012 qty=3456789", donde el espacio es un limite de campo y no
    un separador de tarjeta. Se deja apagado porque tambien descartaria un PAN
    filtrado con un formato inesperado, que es justo lo que no queremos perder.
    """
    grupos = [len(g) for g in re.split("[%s]" % re.escape(SEPARADORES), texto) if g]
    if len(grupos) == 1:
        return True  # sin separadores
    if grupos == [4, 6, 5]:
        return True  # formato de 15 digitos
    return all(g == 4 for g in grupos[:-1]) and 1 <= grupos[-1] <= 4


@dataclass(frozen=True)
class Hallazgo:
    """Un PAN detectado, descrito sin exponerlo.

    `posicion` es el desplazamiento en caracteres desde el inicio de la fuente.
    En archivos leidos como bytes equivale al desplazamiento en bytes.
    `enmascarado` es None salvo que se pida explicitamente al buscar.
    """

    fuente: str
    posicion: int
    longitud: int
    sha256: str
    con_separadores: bool
    enmascarado: str = field(default=None)

    def a_dict(self):
        """Forma serializable del hallazgo. Nunca incluye el PAN completo."""
        d = {
            "fuente": self.fuente,
            "posicion": self.posicion,
            "longitud": self.longitud,
            "sha256": self.sha256,
            "con_separadores": self.con_separadores,
        }
        if self.enmascarado is not None:
            d["enmascarado"] = self.enmascarado
        return d

    def __repr__(self):
        # Se sobreescribe el repr generado por dataclass para que ni un print
        # de depuracion ni una traza de excepcion puedan filtrar el valor.
        return "Hallazgo(fuente=%r, posicion=%d, longitud=%d, sha256=%s...)" % (
            self.fuente, self.posicion, self.longitud, self.sha256[:12],
        )

    __str__ = __repr__


def buscar_en_texto(texto, fuente="<texto>", enmascarar_valor=False,
                    descartar_triviales=True, exigir_agrupacion=False,
                    desplazamiento=0):
    """Busca PANs en una cadena y devuelve la lista de hallazgos.

    - enmascarar_valor: incluye los ultimos 4 digitos en el hallazgo.
    - descartar_triviales: ignora cadenas de un solo digito repetido.
    - exigir_agrupacion: aplica el filtro de agrupacion tipica (ver arriba).
    - desplazamiento: se suma a la posicion, para lectura por bloques.
    """
    hallazgos = []
    for m in _PATRON.finditer(texto):
        bruto = m.group(0)
        digitos = normalizar(bruto)
        if not (LONGITUD_MIN <= len(digitos) <= LONGITUD_MAX):
            continue
        if not luhn_valido(digitos):
            continue
        if descartar_triviales and _es_trivial(digitos):
            continue
        if exigir_agrupacion and not _agrupacion_plausible(bruto):
            continue
        hallazgos.append(
            Hallazgo(
                fuente=fuente,
                posicion=desplazamiento + m.start(),
                longitud=len(digitos),
                sha256=huella(digitos),
                con_separadores=len(bruto) != len(digitos),
                enmascarado=enmascarar(digitos) if enmascarar_valor else None,
            )
        )
    return hallazgos


def buscar_en_archivo(ruta, **opciones):
    """Busca PANs en un archivo local, por bloques.

    El contenido se decodifica como latin-1: nunca falla y conserva la
    correspondencia byte-caracter, asi que sirve igual para un log de texto que
    para una captura binaria.
    """
    ruta = Path(ruta)
    fuente = opciones.pop("fuente", str(ruta))
    hallazgos = []
    vistos = set()  # posiciones ya reportadas, por el solape entre bloques
    with open(ruta, "rb") as fh:
        leidos = 0
        resto = ""
        while True:
            bloque = fh.read(TAM_BLOQUE)
            if not bloque:
                break
            texto = resto + bloque.decode("latin-1")
            inicio = leidos - len(resto)
            for h in buscar_en_texto(texto, fuente=fuente, desplazamiento=inicio, **opciones):
                if h.posicion not in vistos:
                    vistos.add(h.posicion)
                    hallazgos.append(h)
            leidos += len(bloque)
            resto = texto[-SOLAPE:]
    return hallazgos


def resumen(hallazgos):
    """Resumen agregado, apto para el reporte de evidencia."""
    return {
        "hay_pan": bool(hallazgos),
        "total_hallazgos": len(hallazgos),
        "valores_distintos": len({h.sha256 for h in hallazgos}),
        "fuentes": sorted({h.fuente for h in hallazgos}),
        "hallazgos": [h.a_dict() for h in hallazgos],
    }


if __name__ == "__main__":
    # Uso: python -m captura.detector_pan <archivo> [...]
    # Salida 0 si no encontro nada, 1 si encontro algun PAN.
    import json
    import sys

    if len(sys.argv) < 2:
        print("uso: python -m captura.detector_pan <archivo> [...]")
        raise SystemExit(2)

    todos = []
    for arg in sys.argv[1:]:
        todos.extend(buscar_en_archivo(arg))
    print(json.dumps(resumen(todos), indent=2, ensure_ascii=False))
    raise SystemExit(1 if todos else 0)
