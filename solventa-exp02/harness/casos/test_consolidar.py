# -*- coding: utf-8 -*-
"""Pruebas de la consolidacion de resultados de EXP-02.

Lo que se prueba aqui no es el sistema de Solventa sino la aritmetica del
reporte: que un caso no ejecutado no se convierta en un PASS, que un control
no infle el porcentaje del criterio que protege y que un denominador vacio no
produzca un 100%. Un error en este modulo se traduce en afirmar ante el tutor
algo que la corrida no demostro.

Ejecucion, desde solventa-exp02/harness:

    python -m unittest casos.test_consolidar -v
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidencia import consolidar as C  # noqa: E402
from veredicto import Veredicto  # noqa: E402

CASOS, _ = C.cargar_catalogo()

# Casos de tipo prueba por criterio, segun el catalogo.
PRUEBAS = {
    crit: sorted(c["id"] for c in CASOS.values()
                 if c["criterio"] == crit and c["tipo"] == "prueba")
    for crit in ("C1", "C2", "C3", "C4", "habilitante")
}
CONTROLES = {
    crit: sorted(c["id"] for c in CASOS.values()
                 if c["criterio"] == crit and c["tipo"] == "control")
    for crit in ("C1", "C2", "C3", "C4")
}


def res(**por_caso):
    """Construye la lista de Resultado a partir de {caso_id: Veredicto}."""
    return [C.Resultado(caso=k.replace("_", "-"), veredicto=v)
            for k, v in por_caso.items()]


def todos(veredicto=Veredicto.PASS, excepto=None):
    """Todos los casos del catalogo con el mismo veredicto, salvo excepciones."""
    excepto = excepto or {}
    return [C.Resultado(caso=cid, veredicto=excepto.get(cid, veredicto))
            for cid in CASOS]


class TestCatalogo(unittest.TestCase):
    """El catalogo es el contrato de entrada de la consolidacion."""

    def test_estan_los_16_casos_previstos(self):
        esperados = {
            "MTLS-01", "MTLS-02", "MTLS-03",
            "CONF-01", "CONF-02", "CONF-03", "CONF-04", "CONF-99",
            "PERS-01", "PERS-02", "PERS-03",
            "INTEG-01", "INTEG-02", "INTEG-03", "INTEG-04", "INTEG-05",
        }
        self.assertEqual(set(CASOS), esperados)

    def test_cada_caso_declara_los_campos_obligatorios(self):
        obligatorios = ("id", "criterio", "descripcion", "tipo",
                        "resultado_esperado", "responsable", "dependencia",
                        "artefactos_esperados")
        for cid, caso in CASOS.items():
            with self.subTest(caso=cid):
                for campo in obligatorios:
                    self.assertIn(campo, caso)
                    self.assertTrue(caso[campo], "campo vacio: %s" % campo)
                self.assertIn(caso["criterio"], ("C1", "C2", "C3", "C4", "habilitante"))
                self.assertIn(caso["tipo"], ("prueba", "control"))

    def test_los_controles_son_conf99_y_pers03(self):
        self.assertEqual(CONTROLES["C1"], ["CONF-99"])
        self.assertEqual(CONTROLES["C2"], ["PERS-03"])


class TestA_TodoPasa(unittest.TestCase):
    """A. Todos los casos medidos pasan."""

    def setUp(self):
        self.r = C.consolidar(todos(Veredicto.PASS), modo="real")

    def test_los_cuatro_criterios_cumplen(self):
        for cid in ("C1", "C2", "C3", "C4"):
            with self.subTest(criterio=cid):
                self.assertEqual(self.r["criterios"][cid]["estado"], C.CUMPLE)
                self.assertEqual(self.r["criterios"][cid]["porcentaje"], 100.0)

    def test_estado_global_cumple(self):
        self.assertEqual(self.r["estado_global"], C.CUMPLE)

    def test_no_quedan_casos_sin_resultado(self):
        self.assertEqual(self.r["casos_sin_resultado"], [])


class TestB_FallaReal(unittest.TestCase):
    """B. Existe un FAIL real."""

    def setUp(self):
        self.r = C.consolidar(
            todos(Veredicto.PASS, excepto={"INTEG-02": Veredicto.FAIL}), modo="real")

    def test_el_criterio_afectado_no_cumple(self):
        c4 = self.r["criterios"]["C4"]
        self.assertEqual(c4["estado"], C.NO_CUMPLE)
        self.assertEqual(c4["pruebas_fail"], 1)

    def test_los_demas_criterios_no_se_contagian(self):
        for cid in ("C1", "C2", "C3"):
            with self.subTest(criterio=cid):
                self.assertEqual(self.r["criterios"][cid]["estado"], C.CUMPLE)

    def test_estado_global_refleja_el_fallo(self):
        self.assertEqual(self.r["estado_global"], C.NO_CUMPLE)


class TestC_NoDisponible(unittest.TestCase):
    """C. Hay NO_DISPONIBLE."""

    def setUp(self):
        self.r = C.consolidar(
            todos(Veredicto.PASS, excepto={"CONF-04": Veredicto.NO_DISPONIBLE}),
            modo="real")
        self.c1 = self.r["criterios"]["C1"]

    def test_no_disponible_no_cuenta_como_pass(self):
        self.assertEqual(self.c1["pruebas_pass"], len(PRUEBAS["C1"]) - 1)
        self.assertEqual(self.c1["pendientes"]["NO_DISPONIBLE"], 1)

    def test_queda_fuera_del_denominador(self):
        self.assertEqual(self.c1["denominador"], len(PRUEBAS["C1"]) - 1)

    def test_el_criterio_queda_incompleto_no_cumplido(self):
        # El porcentaje sobre lo evaluado es 100 %, pero el criterio NO se da
        # por cumplido: queda un caso sin ejecutar.
        self.assertEqual(self.c1["porcentaje"], 100.0)
        self.assertEqual(self.c1["estado"], C.INCOMPLETO)
        self.assertNotEqual(self.c1["estado"], C.CUMPLE)

    def test_un_caso_sin_resultado_se_cuenta_como_no_disponible(self):
        # Ausencia de reporte no es ausencia de caso.
        parciales = [r for r in todos(Veredicto.PASS) if r.caso != "CONF-03"]
        r = C.consolidar(parciales, modo="real")
        self.assertEqual(r["criterios"]["C1"]["detalle"]["CONF-03"], "NO_DISPONIBLE")
        self.assertEqual(r["casos_sin_resultado"], ["CONF-03"])


class TestD_ContratoRoto(unittest.TestCase):
    """D. Hay CONTRATO_ROTO."""

    def setUp(self):
        self.r = C.consolidar(
            todos(Veredicto.PASS, excepto={"PERS-02": Veredicto.CONTRATO_ROTO}),
            modo="real")
        self.c2 = self.r["criterios"]["C2"]

    def test_no_se_interpreta_como_fallo_de_seguridad(self):
        self.assertEqual(self.c2["pruebas_fail"], 0)
        self.assertNotEqual(self.c2["estado"], C.NO_CUMPLE)

    def test_tampoco_permite_dar_el_criterio_por_cumplido(self):
        self.assertEqual(self.c2["estado"], C.INCOMPLETO)
        self.assertEqual(self.c2["pendientes"]["CONTRATO_ROTO"], 1)

    def test_el_motivo_queda_explicito_en_el_reporte(self):
        self.assertTrue(any("CONTRATO_ROTO" in m for m in self.c2["motivos"]))


class TestE_ErrorArnes(unittest.TestCase):
    """E. Hay ERROR_ARNES."""

    def setUp(self):
        self.r = C.consolidar(
            todos(Veredicto.PASS, excepto={"INTEG-04": Veredicto.ERROR_ARNES}),
            modo="real")
        self.c4 = self.r["criterios"]["C4"]

    def test_invalida_la_evaluacion_del_criterio(self):
        self.assertEqual(self.c4["estado"], C.INVALIDADO)

    def test_no_se_atribuye_al_sistema(self):
        self.assertEqual(self.c4["pruebas_fail"], 0)
        self.assertTrue(any("ERROR_ARNES" in m for m in self.c4["motivos"]))

    def test_los_conteos_se_conservan(self):
        # Invalidar no borra lo medido: el reporte sigue mostrando el detalle.
        self.assertEqual(self.c4["pruebas_pass"], len(PRUEBAS["C4"]) - 1)
        self.assertEqual(self.c4["pendientes"]["ERROR_ARNES"], 1)


class TestF_DenominadorCero(unittest.TestCase):
    """F. Denominador 0."""

    def setUp(self):
        sin_c3 = {cid: Veredicto.NO_DISPONIBLE for cid in PRUEBAS["C3"]}
        self.r = C.consolidar(
            todos(Veredicto.PASS, excepto=sin_c3), modo="real")
        self.c3 = self.r["criterios"]["C3"]

    def test_no_se_calcula_porcentaje(self):
        self.assertEqual(self.c3["denominador"], 0)
        self.assertIsNone(self.c3["porcentaje"],
                          "con denominador 0 el porcentaje no existe")

    def test_el_criterio_queda_no_verificado(self):
        self.assertEqual(self.c3["estado"], C.NO_VERIFICADO)
        self.assertNotEqual(self.c3["estado"], C.CUMPLE)

    def test_el_reporte_lo_dice_explicitamente(self):
        md = C.a_markdown(self.r)
        self.assertIn("n/d (denominador 0)", md)


class TestG_ControlConf99(unittest.TestCase):
    """G. CONF-99 falla y por tanto invalida confidencialidad."""

    def setUp(self):
        self.r = C.consolidar(
            todos(Veredicto.PASS, excepto={"CONF-99": Veredicto.FAIL}), modo="real")
        self.c1 = self.r["criterios"]["C1"]

    def test_c1_queda_invalidado_pese_a_cero_hallazgos(self):
        # Todas las busquedas de PAN dieron PASS (cero hallazgos), pero el
        # detector no quedo demostrado: el criterio no se puede sostener.
        self.assertEqual(self.c1["pruebas_pass"], len(PRUEBAS["C1"]))
        self.assertEqual(self.c1["porcentaje"], 100.0)
        self.assertEqual(self.c1["estado"], C.INVALIDADO)

    def test_el_motivo_menciona_el_control(self):
        self.assertTrue(any("CONF-99" in m for m in self.c1["motivos"]))

    def test_un_control_no_ejecutado_tambien_invalida(self):
        # No demostrar el instrumento equivale a no poder confiar en el.
        r = C.consolidar(
            todos(Veredicto.PASS, excepto={"CONF-99": Veredicto.NO_DISPONIBLE}),
            modo="real")
        self.assertEqual(r["criterios"]["C1"]["estado"], C.INVALIDADO)

    def test_pers03_protege_a_c2_del_mismo_modo(self):
        r = C.consolidar(
            todos(Veredicto.PASS, excepto={"PERS-03": Veredicto.FAIL}), modo="real")
        self.assertEqual(r["criterios"]["C2"]["estado"], C.INVALIDADO)

    def test_el_fallo_de_un_control_no_contagia_a_otros_criterios(self):
        for cid in ("C2", "C3", "C4"):
            with self.subTest(criterio=cid):
                self.assertEqual(self.r["criterios"][cid]["estado"], C.CUMPLE)


class TestH_ControlesNoSonObservaciones(unittest.TestCase):
    """H. Los controles no cuentan como observaciones normales."""

    def setUp(self):
        self.r = C.consolidar(todos(Veredicto.PASS), modo="real")

    def test_el_denominador_excluye_los_controles(self):
        c1 = self.r["criterios"]["C1"]
        self.assertEqual(c1["denominador"], len(PRUEBAS["C1"]))
        self.assertEqual(len(CONTROLES["C1"]), 1)
        self.assertNotIn("CONF-99", c1["detalle"],
                         "el control no debe aparecer entre las observaciones")

    def test_el_control_se_reporta_aparte(self):
        self.assertEqual(self.r["criterios"]["C1"]["controles"], {"CONF-99": "PASS"})

    def test_un_control_en_pass_no_sube_el_porcentaje(self):
        # Con una prueba en FAIL, el control en PASS no debe compensarla.
        r = C.consolidar(
            todos(Veredicto.PASS, excepto={"CONF-02": Veredicto.FAIL}), modo="real")
        c1 = r["criterios"]["C1"]
        esperado = (len(PRUEBAS["C1"]) - 1) / len(PRUEBAS["C1"]) * 100
        self.assertAlmostEqual(c1["porcentaje"], esperado)
        self.assertEqual(c1["denominador"], len(PRUEBAS["C1"]))


class TestI_MezclaPassFail(unittest.TestCase):
    """I. Mezcla de PASS y FAIL calcula correctamente el porcentaje."""

    def test_tres_de_cuatro(self):
        self.assertEqual(len(PRUEBAS["C4"]), 4)
        r = C.consolidar(
            todos(Veredicto.PASS, excepto={"INTEG-05": Veredicto.FAIL}), modo="real")
        c4 = r["criterios"]["C4"]
        self.assertEqual((c4["pruebas_pass"], c4["pruebas_fail"]), (3, 1))
        self.assertEqual(c4["denominador"], 4)
        self.assertEqual(c4["porcentaje"], 75.0)
        self.assertEqual(c4["estado"], C.NO_CUMPLE)

    def test_el_denominador_ignora_lo_no_evaluado(self):
        # 2 PASS, 1 FAIL, 1 NO_DISPONIBLE -> 66.67 % sobre 3, no sobre 4.
        r = C.consolidar(
            todos(Veredicto.PASS, excepto={
                "INTEG-05": Veredicto.FAIL,
                "INTEG-04": Veredicto.NO_DISPONIBLE,
            }), modo="real")
        c4 = r["criterios"]["C4"]
        self.assertEqual(c4["denominador"], 3)
        self.assertAlmostEqual(c4["porcentaje"], 200 / 3)


class TestValidezDeLaEvidencia(unittest.TestCase):
    """Solo MODO=real sustenta el experimento."""

    def test_modo_real_marca_la_evidencia_como_valida(self):
        self.assertTrue(C.consolidar(todos(), modo="real")["evidencia_valida"])

    def test_modo_simulado_y_mixto_no(self):
        for modo in ("simulado", "mixto", None):
            with self.subTest(modo=modo):
                r = C.consolidar(todos(), modo=modo)
                self.assertFalse(r["evidencia_valida"])
                self.assertIn("EVIDENCIA NO VALIDA", C.a_markdown(r))

    def test_el_reporte_real_no_lleva_la_marca(self):
        self.assertNotIn("EVIDENCIA NO VALIDA",
                         C.a_markdown(C.consolidar(todos(), modo="real")))


class TestEntradasInvalidas(unittest.TestCase):
    """Un reporte incorrecto en silencio es peor que un error ruidoso."""

    def test_resultado_de_un_caso_ausente_del_catalogo(self):
        with self.assertRaises(ValueError):
            C.consolidar([C.Resultado(caso="NO-EXISTE", veredicto=Veredicto.PASS)])

    def test_resultado_duplicado(self):
        with self.assertRaises(ValueError):
            C.consolidar([
                C.Resultado(caso="CONF-01", veredicto=Veredicto.PASS),
                C.Resultado(caso="CONF-01", veredicto=Veredicto.FAIL),
            ])

    def test_tipo_incorrecto(self):
        with self.assertRaises(TypeError):
            C.consolidar([{"caso": "CONF-01", "veredicto": "PASS"}])

    def test_sin_resultados_todo_queda_no_verificado(self):
        r = C.consolidar([])
        for cid in ("C1", "C2", "C3", "C4"):
            with self.subTest(criterio=cid):
                self.assertIn(r["criterios"][cid]["estado"],
                              (C.NO_VERIFICADO, C.INVALIDADO))
                self.assertIsNone(r["criterios"][cid]["porcentaje"])


class TestSalida(unittest.TestCase):
    """El resumen debe poder guardarse como evidencia."""

    def test_el_resumen_es_serializable(self):
        json.dumps(C.consolidar(todos(), modo="real"))

    def test_el_markdown_conserva_el_denominador(self):
        md = C.a_markdown(C.consolidar(todos(), modo="real"))
        self.assertIn("100.00 %% de %d" % len(PRUEBAS["C1"]), md)

    def test_los_habilitantes_se_reportan_aparte_de_los_criterios(self):
        r = C.consolidar(todos(), modo="real")
        self.assertNotIn("habilitante", r["criterios"])
        self.assertEqual(set(r["habilitantes"]["detalle"]), set(PRUEBAS["habilitante"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
