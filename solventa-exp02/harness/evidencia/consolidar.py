# -*- coding: utf-8 -*-
"""Consolidacion de resultados de EXP-02 en los cuatro criterios oficiales.

Recibe los veredictos de los casos y produce el resumen por criterio. No
ejecuta casos, no habla con ningun servicio y no inventa resultados: si un caso
no reporto nada, se cuenta como NO_DISPONIBLE.

Reglas de agregacion, todas pensadas para que el reporte no pueda afirmar mas
de lo que la corrida demostro:

1. Denominador explicito. El porcentaje se calcula solo sobre casos de tipo
   prueba efectivamente evaluados (PASS o FAIL) y siempre se acompana del
   denominador. Con denominador 0 el porcentaje es None, nunca 0 ni 100.
2. NO_DISPONIBLE no es PASS. Un caso que no se pudo ejecutar queda fuera del
   numerador y del denominador, y se reporta como pendiente.
3. CONTRATO_ROTO no es un fallo de seguridad. Es un desajuste de integracion:
   no acusa al sistema, pero tampoco permite dar el criterio por cumplido.
4. ERROR_ARNES invalida el criterio. Si el instrumento fallo, ningun veredicto
   de ese criterio es confiable.
5. Los controles no inflan el porcentaje. CONF-99 y PERS-03 no suman al
   numerador ni al denominador de su criterio; pero si un control no da PASS,
   el criterio queda INVALIDADO. Es el caso de CONF-99: un detector averiado
   reporta cero hallazgos siempre, asi que "cero PAN encontrados" no significa
   nada mientras no se demuestre que el detector ve.

Los conteos se conservan siempre, incluso cuando el criterio queda invalidado:
un FAIL real no debe desaparecer del reporte porque otra cosa fallara.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from veredicto import Veredicto

RUTA_CATALOGO = Path(__file__).resolve().parents[1] / "fixtures" / "casos.json"

# Estado de un criterio, en orden de precedencia: el primero que aplique gana.
INVALIDADO = "INVALIDADO"        # el instrumento o el arnes no son confiables
NO_CUMPLE = "NO_CUMPLE"          # hay al menos un fallo real
NO_VERIFICADO = "NO_VERIFICADO"  # no se evaluo ningun caso
INCOMPLETO = "INCOMPLETO"        # lo evaluado paso, pero quedan casos pendientes
CUMPLE = "CUMPLE"                # todo lo evaluado paso y no queda nada pendiente

PRECEDENCIA = [INVALIDADO, NO_CUMPLE, NO_VERIFICADO, INCOMPLETO, CUMPLE]

CRITERIO_HABILITANTE = "habilitante"


@dataclass
class Resultado:
    """Veredicto reportado para un caso del catalogo."""

    caso: str
    veredicto: Veredicto
    nota: str = ""
    artefactos: list = field(default_factory=list)

    def a_dict(self):
        return {
            "caso": self.caso,
            "veredicto": self.veredicto.value,
            "nota": self.nota,
            "artefactos": list(self.artefactos),
        }


def cargar_catalogo(ruta=None):
    """Lee casos.json y devuelve {id: caso} mas los enunciados de criterio."""
    with open(ruta or RUTA_CATALOGO, encoding="utf-8") as fh:
        datos = json.load(fh)
    casos = {c["id"]: c for c in datos["casos"]}
    if len(casos) != len(datos["casos"]):
        raise ValueError("el catalogo tiene ids de caso repetidos")
    return casos, datos.get("_criterios", {})


def _indexar_resultados(resultados, casos):
    """Valida los resultados recibidos y los indexa por caso.

    Un resultado para un caso que no esta en el catalogo, o dos resultados para
    el mismo caso, son errores de programacion del arnes: se avisa de inmediato
    en vez de producir un reporte silenciosamente incorrecto.
    """
    indice = {}
    for r in resultados:
        if not isinstance(r, Resultado):
            raise TypeError("se esperaba Resultado, llego %r" % type(r).__name__)
        if r.caso not in casos:
            raise ValueError("resultado para un caso ausente del catalogo: %s" % r.caso)
        if r.caso in indice:
            raise ValueError("resultado duplicado para el caso %s" % r.caso)
        indice[r.caso] = r
    return indice


def _estado(pruebas_fail, evaluadas, pendientes, controles_fallidos, hubo_error_arnes):
    """Aplica la precedencia de estados de un criterio."""
    if hubo_error_arnes or controles_fallidos:
        return INVALIDADO
    if pruebas_fail:
        return NO_CUMPLE
    if evaluadas == 0:
        return NO_VERIFICADO
    if pendientes:
        return INCOMPLETO
    return CUMPLE


def _consolidar_criterio(criterio, enunciado, casos_criterio, indice):
    pruebas = [c for c in casos_criterio if c["tipo"] == "prueba"]
    controles = [c for c in casos_criterio if c["tipo"] == "control"]

    def veredicto_de(caso):
        r = indice.get(caso["id"])
        return r.veredicto if r else Veredicto.NO_DISPONIBLE

    # Solo las pruebas entran en el porcentaje. Los controles quedan fuera para
    # no inflar el resultado del criterio que protegen.
    v_pruebas = {c["id"]: veredicto_de(c) for c in pruebas}
    n_pass = sum(1 for v in v_pruebas.values() if v is Veredicto.PASS)
    n_fail = sum(1 for v in v_pruebas.values() if v is Veredicto.FAIL)
    evaluadas = n_pass + n_fail

    pendientes = {
        Veredicto.NO_DISPONIBLE.value: sum(
            1 for v in v_pruebas.values() if v is Veredicto.NO_DISPONIBLE),
        Veredicto.CONTRATO_ROTO.value: sum(
            1 for v in v_pruebas.values() if v is Veredicto.CONTRATO_ROTO),
        Veredicto.ERROR_ARNES.value: sum(
            1 for v in v_pruebas.values() if v is Veredicto.ERROR_ARNES),
    }
    n_pendientes = pendientes[Veredicto.NO_DISPONIBLE.value] + pendientes[Veredicto.CONTRATO_ROTO.value]

    v_controles = {c["id"]: veredicto_de(c) for c in controles}
    controles_fallidos = [cid for cid, v in v_controles.items() if v is not Veredicto.PASS]
    hubo_error_arnes = (
        pendientes[Veredicto.ERROR_ARNES.value] > 0
        or any(v is Veredicto.ERROR_ARNES for v in v_controles.values())
    )

    estado = _estado(n_fail, evaluadas, n_pendientes, controles_fallidos, hubo_error_arnes)

    motivos = []
    for cid in controles_fallidos:
        motivos.append(
            "el control %s no dio PASS (%s): el instrumento de %s no quedo "
            "demostrado, asi que sus resultados no son concluyentes"
            % (cid, v_controles[cid].value, criterio))
    if hubo_error_arnes:
        motivos.append(
            "hubo ERROR_ARNES en %s: el fallo es del arnes, no del sistema, y "
            "deja la evaluacion sin validez" % criterio)
    if pendientes[Veredicto.CONTRATO_ROTO.value]:
        motivos.append(
            "%d caso(s) con CONTRATO_ROTO: desajuste de integracion, no fallo "
            "de seguridad; impide dar el criterio por cumplido"
            % pendientes[Veredicto.CONTRATO_ROTO.value])
    if pendientes[Veredicto.NO_DISPONIBLE.value]:
        motivos.append(
            "%d caso(s) NO_DISPONIBLE: no se ejecutaron y no cuentan como PASS"
            % pendientes[Veredicto.NO_DISPONIBLE.value])
    if evaluadas == 0:
        motivos.append("denominador 0: no se evaluo ninguna prueba, el porcentaje no existe")

    return {
        "criterio": criterio,
        "enunciado": enunciado,
        "estado": estado,
        # Denominador explicito: nunca se publica un porcentaje sin el.
        "denominador": evaluadas,
        "pruebas_evaluadas": evaluadas,
        "pruebas_pass": n_pass,
        "pruebas_fail": n_fail,
        "porcentaje": (n_pass / evaluadas * 100) if evaluadas else None,
        "pendientes": pendientes,
        "controles": {cid: v.value for cid, v in v_controles.items()},
        "controles_fallidos": controles_fallidos,
        "motivos": motivos,
        "detalle": {cid: v.value for cid, v in sorted(v_pruebas.items())},
    }


def consolidar(resultados, catalogo=None, run_id=None, modo=None):
    """Consolida los resultados de una corrida.

    `resultados` es una lista de Resultado. Los casos del catalogo sin
    resultado se cuentan como NO_DISPONIBLE: un caso que no corrio no puede
    desaparecer del reporte.
    """
    casos, enunciados = catalogo if catalogo else cargar_catalogo()
    indice = _indexar_resultados(resultados, casos)

    criterios = {}
    for criterio in ("C1", "C2", "C3", "C4"):
        del_criterio = [c for c in casos.values() if c["criterio"] == criterio]
        criterios[criterio] = _consolidar_criterio(
            criterio, enunciados.get(criterio, ""), del_criterio, indice)

    habilitantes = [c for c in casos.values() if c["criterio"] == CRITERIO_HABILITANTE]
    hab = _consolidar_criterio(
        CRITERIO_HABILITANTE, enunciados.get(CRITERIO_HABILITANTE, ""),
        habilitantes, indice)

    estados = [c["estado"] for c in criterios.values()]
    global_ = next(e for e in PRECEDENCIA if e in estados)

    return {
        "run_id": run_id,
        "modo": modo,
        # Solo una corrida en modo real sustenta el experimento. None = no
        # declarado, que tampoco es evidencia valida.
        "evidencia_valida": (modo == "real"),
        "criterios": criterios,
        "habilitantes": hab,
        "estado_global": global_,
        "casos_sin_resultado": sorted(set(casos) - set(indice)),
        "resultados": [indice[k].a_dict() for k in sorted(indice)],
    }


def _pct(criterio):
    if criterio["porcentaje"] is None:
        return "n/d (denominador 0)"
    return "%.2f %% de %d" % (criterio["porcentaje"], criterio["denominador"])


def a_markdown(resumen):
    """Reporte legible. Refleja el resumen tal cual, sin redondear conclusiones."""
    lineas = []
    if not resumen["evidencia_valida"]:
        lineas += [
            "> **EVIDENCIA NO VALIDA** - modo `%s`. Solo una corrida en modo "
            "`real` sustenta el experimento." % (resumen["modo"] or "no declarado"),
            "",
        ]
    lineas += [
        "# EXP-02 - Consolidacion de resultados",
        "",
        "- run_id: `%s`" % (resumen["run_id"] or "no declarado"),
        "- modo: `%s`" % (resumen["modo"] or "no declarado"),
        "- estado global: **%s**" % resumen["estado_global"],
        "",
        "## Criterios",
        "",
        "| Criterio | Estado | PASS/evaluadas | Porcentaje | Pendientes |",
        "|---|---|---|---|---|",
    ]
    for cid in ("C1", "C2", "C3", "C4"):
        c = resumen["criterios"][cid]
        pend = sum(c["pendientes"].values())
        lineas.append("| %s | %s | %d/%d | %s | %d |" % (
            cid, c["estado"], c["pruebas_pass"], c["denominador"], _pct(c), pend))

    for cid in ("C1", "C2", "C3", "C4"):
        c = resumen["criterios"][cid]
        lineas += ["", "### %s - %s" % (cid, c["enunciado"]), "",
                   "- estado: **%s**" % c["estado"],
                   "- pruebas: %d PASS, %d FAIL, denominador %d"
                   % (c["pruebas_pass"], c["pruebas_fail"], c["denominador"])]
        if c["controles"]:
            lineas.append("- controles: %s" % ", ".join(
                "%s=%s" % (k, v) for k, v in sorted(c["controles"].items())))
        for m in c["motivos"]:
            lineas.append("- %s" % m)
        lineas.append("- detalle: %s" % ", ".join(
            "%s=%s" % (k, v) for k, v in c["detalle"].items()))

    hab = resumen["habilitantes"]
    lineas += ["", "## Habilitantes (no son criterios oficiales)", "",
               "- estado: %s" % hab["estado"],
               "- detalle: %s" % ", ".join(
                   "%s=%s" % (k, v) for k, v in hab["detalle"].items())]
    if resumen["casos_sin_resultado"]:
        lineas += ["", "## Casos sin resultado reportado", "",
                   ", ".join(resumen["casos_sin_resultado"])]
    return "\n".join(lineas) + "\n"


def leer_resultados(ruta):
    """Carga resultados desde un JSON producido por una corrida."""
    with open(ruta, encoding="utf-8") as fh:
        datos = json.load(fh)
    resultados = [
        Resultado(
            caso=r["caso"],
            veredicto=Veredicto(r["veredicto"]),
            nota=r.get("nota", ""),
            artefactos=r.get("artefactos", []),
        )
        for r in datos.get("resultados", [])
    ]
    return resultados, datos.get("run_id"), datos.get("modo")


if __name__ == "__main__":
    # Uso: python -m evidencia.consolidar <resultados.json> [--json]
    import sys

    if len(sys.argv) < 2:
        print("uso: python -m evidencia.consolidar <resultados.json> [--json]")
        raise SystemExit(2)

    resultados, run_id, modo = leer_resultados(sys.argv[1])
    resumen = consolidar(resultados, run_id=run_id, modo=modo)
    if "--json" in sys.argv[2:]:
        print(json.dumps(resumen, indent=2, ensure_ascii=False))
    else:
        print(a_markdown(resumen))
    raise SystemExit(0 if resumen["estado_global"] == CUMPLE else 1)
