# -*- coding: utf-8 -*-
"""Estados posibles del resultado de un caso del arnes de EXP-02.

Este modulo define UNICAMENTE el vocabulario de veredictos y como se agregan.
No ejecuta casos, no mide nada y no conoce ningun componente del sistema.

La distincion central del EXP-02 es que "no se pudo verificar" NO es lo mismo
que "se verifico y esta bien". Un criterio de seguridad que no pudo evaluarse
queda sin demostrar, y reportarlo como cumplido seria el peor error posible del
arnes. Por eso NO_DISPONIBLE se trata aqui como un estado de primera clase y
nunca colapsa a PASS.
"""

from enum import Enum


class Veredicto(Enum):
    """Resultado de la ejecucion de un caso."""

    # El caso se ejecuto y el sistema se comporto como exige el criterio.
    PASS = "PASS"

    # El caso se ejecuto y el sistema NO cumplio el criterio. Hallazgo real.
    FAIL = "FAIL"

    # El caso no pudo ejecutarse: el componente todavia no existe, no responde
    # o el entorno no esta listo. No dice nada sobre el criterio.
    NO_DISPONIBLE = "NO_DISPONIBLE"

    # El componente respondio, pero no en la forma acordada en el contrato.
    # No es un fallo de seguridad: es un desajuste de integracion que hay que
    # reportarle al dueno del componente antes de poder evaluar el criterio.
    CONTRATO_ROTO = "CONTRATO_ROTO"

    # Fallo el propio arnes (bug, excepcion inesperada, artefacto ilegible).
    # Se separa de FAIL para no atribuirle al sistema un error nuestro.
    ERROR_ARNES = "ERROR_ARNES"

    def __str__(self):
        return self.value

    # -- Semantica -----------------------------------------------------------

    @property
    def es_pass(self):
        """True solo para PASS. Unica forma admitida de preguntar por exito."""
        return self is Veredicto.PASS

    @property
    def fue_evaluado(self):
        """True si el caso llego a producir un juicio sobre el criterio.

        NO_DISPONIBLE, CONTRATO_ROTO y ERROR_ARNES no evaluaron el criterio:
        no pueden sumar ni al numerador ni al denominador de un porcentaje.
        """
        return self in (Veredicto.PASS, Veredicto.FAIL)

    @property
    def requiere_atencion(self):
        """True si el veredicto exige accion antes de la sustentacion."""
        return self is not Veredicto.PASS

    def __bool__(self):
        # Guarda deliberada. `if veredicto:` seria verdadero para NO_DISPONIBLE
        # con la semantica por defecto de Enum, que es exactamente el error que
        # este modulo existe para impedir. Obligamos a escribir `.es_pass`.
        raise TypeError(
            "Un Veredicto no se evalua como booleano: usa .es_pass o compara "
            "explicitamente (veredicto is Veredicto.PASS)."
        )


# Codigos de salida del proceso. Permiten encadenar el arnes en un script o en
# CI sin tener que parsear el reporte.
SALIDA_OK = 0            # todos los casos evaluados dieron PASS
SALIDA_FALLO = 1         # al menos un FAIL: hallazgo de seguridad
SALIDA_INCOMPLETO = 2    # nada fallo, pero quedaron casos sin evaluar
SALIDA_ERROR_ARNES = 3   # el arnes no pudo hacer su trabajo


def resumir(veredictos):
    """Cuenta los veredictos de una corrida.

    Devuelve un dict con el conteo por estado mas los agregados que necesita
    el reporte. `evaluados` es el denominador honesto de cualquier porcentaje:
    los casos no evaluados quedan fuera y se reportan aparte.
    """
    conteo = {v: 0 for v in Veredicto}
    for v in veredictos:
        if not isinstance(v, Veredicto):
            raise TypeError("Se esperaba un Veredicto, llego %r" % type(v).__name__)
        conteo[v] += 1

    evaluados = conteo[Veredicto.PASS] + conteo[Veredicto.FAIL]
    return {
        "conteo": {v.value: n for v, n in conteo.items()},
        "total": sum(conteo.values()),
        "evaluados": evaluados,
        "no_evaluados": sum(conteo.values()) - evaluados,
        # None, no 0 ni 100: sin casos evaluados el porcentaje no existe.
        "porcentaje_pass": (conteo[Veredicto.PASS] / evaluados * 100) if evaluados else None,
    }


def codigo_salida(veredictos):
    """Traduce los veredictos de la corrida al codigo de salida del proceso."""
    conteo = resumir(veredictos)["conteo"]
    if conteo[Veredicto.ERROR_ARNES.value]:
        return SALIDA_ERROR_ARNES
    if conteo[Veredicto.FAIL.value]:
        return SALIDA_FALLO
    if conteo[Veredicto.NO_DISPONIBLE.value] or conteo[Veredicto.CONTRATO_ROTO.value]:
        return SALIDA_INCOMPLETO
    return SALIDA_OK
