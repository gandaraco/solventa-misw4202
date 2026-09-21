# -*- coding: utf-8 -*-
"""CONF-99 - Control positivo del detector de PAN.

CONF-99 no prueba el sistema de Solventa: prueba el arnes. Los criterios 1 y 2
de EXP-02 se demuestran con ausencias ("0 hallazgos", "0 persistencias"), y una
ausencia solo significa algo si antes se demostro que el instrumento sabe
encontrar lo que busca. Un detector averiado produce cero hallazgos siempre, y
haria pasar los dos criterios sin que nadie lo note.

    Si CONF-99 falla, la evidencia de confidencialidad de esa corrida NO es
    valida, aunque todos los demas casos den PASS.

Ejecucion, desde solventa-exp02/harness:

    python -m unittest casos.test_conf99 -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Permite ejecutar el archivo directamente, ademas de via `python -m unittest`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from captura import detector_pan  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pans_sinteticos.json"


def cargar_fixtures():
    with open(FIXTURES, encoding="utf-8") as fh:
        return json.load(fh)


DATOS = cargar_fixtures()


def todos_los_casos():
    """Casos de todos los grupos, con su veredicto esperado."""
    for grupo, casos in DATOS.items():
        if grupo.startswith("_"):
            continue
        for caso in casos:
            yield grupo, caso


class TestCONF99(unittest.TestCase):
    """Control positivo: el detector encuentra lo que debe y nada mas."""

    # -- A: un PAN sintetico Luhn-valido DEBE detectarse -------------------

    def test_A_pan_valido_en_texto_controlado_es_detectado(self):
        pan = DATOS["validos"][0]["valor"]
        texto = "evento=pago_recibido pan=%s monto=150000" % pan
        hallazgos = detector_pan.buscar_en_texto(texto, fuente="CONF-99/A")

        self.assertEqual(len(hallazgos), 1,
                         "el detector no encontro un PAN que si esta presente")
        h = hallazgos[0]
        self.assertEqual(h.longitud, 16)
        self.assertEqual(h.sha256, detector_pan.huella(pan))
        self.assertEqual(texto[h.posicion:h.posicion + h.longitud], pan,
                         "la posicion reportada no apunta al PAN")

    def test_A2_todos_los_pan_validos_de_la_fixture_son_detectados(self):
        for caso in DATOS["validos"]:
            with self.subTest(caso=caso["id"]):
                hallazgos = detector_pan.buscar_en_texto(
                    "pan=%s" % caso["valor"], fuente="CONF-99/A2")
                self.assertEqual(len(hallazgos), 1, caso["nota"])
                self.assertEqual(hallazgos[0].longitud, caso["digitos"])

    # -- B: longitud similar pero Luhn invalido NO es PAN ------------------

    def test_B_numero_luhn_invalido_no_es_considerado_pan(self):
        for caso in DATOS["invalidos_luhn"]:
            with self.subTest(caso=caso["id"]):
                self.assertFalse(detector_pan.luhn_valido(
                    detector_pan.normalizar(caso["valor"])))
                hallazgos = detector_pan.buscar_en_texto(
                    "ref=%s" % caso["valor"], fuente="CONF-99/B")
                self.assertEqual(hallazgos, [], caso["nota"])

    # -- C: PAN con espacios ------------------------------------------------

    def test_C_pan_con_espacios_es_detectado(self):
        for caso in DATOS["con_espacios"]:
            with self.subTest(caso=caso["id"]):
                hallazgos = detector_pan.buscar_en_texto(
                    "tarjeta: %s ." % caso["valor"], fuente="CONF-99/C")
                esperados = 1 if caso["debe_detectarse"] else 0
                self.assertEqual(len(hallazgos), esperados, caso["nota"])
                if esperados:
                    self.assertTrue(hallazgos[0].con_separadores)

    # -- D: PAN con guiones -------------------------------------------------

    def test_D_pan_con_guiones_es_detectado(self):
        for caso in DATOS["con_guiones"]:
            with self.subTest(caso=caso["id"]):
                hallazgos = detector_pan.buscar_en_texto(
                    "tarjeta: %s ." % caso["valor"], fuente="CONF-99/D")
                self.assertEqual(len(hallazgos), 1, caso["nota"])
                self.assertTrue(hallazgos[0].con_separadores)

    def test_D2_el_mismo_pan_con_y_sin_separadores_da_la_misma_huella(self):
        # Permite correlacionar el mismo valor entre artefactos con formatos
        # distintos: log con guiones, cuerpo HTTP sin separadores.
        sin = detector_pan.buscar_en_texto("4111111111111111")[0]
        con_esp = detector_pan.buscar_en_texto("4111 1111 1111 1111")[0]
        con_gui = detector_pan.buscar_en_texto("4111-1111-1111-1111")[0]
        self.assertEqual(sin.sha256, con_esp.sha256)
        self.assertEqual(sin.sha256, con_gui.sha256)

    # -- E: texto sin PAN produce cero hallazgos ----------------------------

    def test_E_texto_sin_pan_no_produce_hallazgos(self):
        for caso in DATOS["textos_sin_pan"]:
            with self.subTest(caso=caso["id"]):
                hallazgos = detector_pan.buscar_en_texto(
                    caso["valor"], fuente="CONF-99/E")
                self.assertEqual(hallazgos, [], caso["nota"])

    def test_E2_cadena_vacia_no_produce_hallazgos(self):
        self.assertEqual(detector_pan.buscar_en_texto(""), [])

    # -- F: el resultado NO contiene el PAN completo ------------------------

    def test_F_el_hallazgo_no_expone_el_pan_completo(self):
        pan = "4111111111111111"
        h = detector_pan.buscar_en_texto("pan=%s" % pan, fuente="CONF-99/F")[0]

        serializado = json.dumps(h.a_dict())
        self.assertNotIn(pan, serializado, "el dict del hallazgo filtra el PAN")
        self.assertNotIn(pan, repr(h), "el repr del hallazgo filtra el PAN")
        self.assertNotIn(pan, str(h), "el str del hallazgo filtra el PAN")

    def test_F2_el_resumen_agregado_no_expone_el_pan(self):
        pan = "5555555555554444"
        hallazgos = detector_pan.buscar_en_texto("a=%s b=%s" % (pan, pan))
        self.assertNotIn(pan, json.dumps(detector_pan.resumen(hallazgos)))

    def test_F3_el_enmascarado_es_opcional_y_solo_deja_4_digitos(self):
        pan = "4111111111111111"
        sin_mascara = detector_pan.buscar_en_texto("pan=%s" % pan)[0]
        self.assertIsNone(sin_mascara.enmascarado,
                          "el enmascarado debe ser opt-in")

        con_mascara = detector_pan.buscar_en_texto(
            "pan=%s" % pan, enmascarar_valor=True)[0]
        self.assertEqual(con_mascara.enmascarado, "************1111")
        self.assertNotIn(pan, json.dumps(con_mascara.a_dict()))

    def test_F4_ningun_valor_de_la_fixture_aparece_completo_en_el_resultado(self):
        for grupo, caso in todos_los_casos():
            with self.subTest(caso=caso["id"]):
                digitos = detector_pan.normalizar(caso["valor"])
                hallazgos = detector_pan.buscar_en_texto(caso["valor"])
                salida = json.dumps(detector_pan.resumen(hallazgos))
                if len(digitos) >= detector_pan.LONGITUD_MIN:
                    self.assertNotIn(digitos, salida)


class TestLimitesDelDetector(unittest.TestCase):
    """Bordes que separan un PAN de un numero cualquiera."""

    def test_longitudes_fuera_de_rango_no_se_reportan(self):
        for caso in DATOS["fuera_de_rango"]:
            with self.subTest(caso=caso["id"]):
                hallazgos = detector_pan.buscar_en_texto(
                    "valor=%s" % caso["valor"])
                self.assertEqual(hallazgos, [], caso["nota"])

    def test_no_se_recorta_un_fragmento_de_una_cadena_mas_larga(self):
        # Una cadena de 20 digitos no debe producir un candidato de 19
        # descartando un extremo.
        self.assertEqual(
            detector_pan.buscar_en_texto("41111111111111111115"), [])

    def test_valor_trivial_se_descarta_por_defecto_pero_es_configurable(self):
        texto = "relleno=0000000000000000"
        self.assertEqual(detector_pan.buscar_en_texto(texto), [])
        self.assertEqual(
            len(detector_pan.buscar_en_texto(texto, descartar_triviales=False)), 1)

    def test_varias_ocurrencias_se_reportan_por_separado(self):
        texto = "a=4111111111111111 b=5555555555554444 c=4111111111111111"
        hallazgos = detector_pan.buscar_en_texto(texto)
        self.assertEqual(len(hallazgos), 3)
        self.assertEqual(detector_pan.resumen(hallazgos)["valores_distintos"], 2)

    def test_luhn_rechaza_entradas_no_numericas(self):
        for entrada in ("", "abcd", "4111-1111", None and ""):
            with self.subTest(entrada=entrada):
                self.assertFalse(detector_pan.luhn_valido(entrada))


class TestDeteccionEnArchivo(unittest.TestCase):
    """El detector debe funcionar igual sobre archivos locales."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="conf99_")

    def tearDown(self):
        for nombre in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, nombre))
        os.rmdir(self.dir)

    def _escribir(self, nombre, contenido):
        ruta = os.path.join(self.dir, nombre)
        with open(ruta, "wb") as fh:
            fh.write(contenido)
        return ruta

    def test_detecta_pan_en_archivo_de_texto(self):
        ruta = self._escribir(
            "log.txt", b"evento=pago pan=4111111111111111 monto=1\n")
        hallazgos = detector_pan.buscar_en_archivo(ruta)
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].fuente, ruta)

    def test_archivo_limpio_no_produce_hallazgos(self):
        ruta = self._escribir(
            "limpio.txt", b"evento=pago token=tok_abc123 ultimos4=1111\n")
        self.assertEqual(detector_pan.buscar_en_archivo(ruta), [])

    def test_detecta_pan_en_contenido_binario(self):
        # Una captura de trafico es binaria: el detector no puede depender de
        # que el archivo sea texto decodificable en UTF-8.
        contenido = b"\x00\x01\xff\xfe" + b"4111111111111111" + b"\x00\xff"
        ruta = self._escribir("captura.bin", contenido)
        self.assertEqual(len(detector_pan.buscar_en_archivo(ruta)), 1)

    def test_detecta_pan_partido_entre_dos_bloques_de_lectura(self):
        # Verifica el solape entre bloques: sin el, un PAN que cae justo en la
        # frontera de 1 MiB se perderia. Ese seria un falso negativo silencioso
        # en una captura grande.
        pan = b"4111111111111111"
        relleno = b"x" * (detector_pan.TAM_BLOQUE - 8)
        ruta = self._escribir("grande.bin", relleno + pan + b"y" * 100)
        hallazgos = detector_pan.buscar_en_archivo(ruta)
        self.assertEqual(len(hallazgos), 1,
                         "se perdio un PAN en la frontera entre bloques")
        self.assertEqual(hallazgos[0].posicion, len(relleno))


if __name__ == "__main__":
    unittest.main(verbosity=2)
