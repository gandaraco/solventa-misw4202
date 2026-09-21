# Arnés de experimentación — EXP-02

Componente de **EXP-02** del proyecto Solventa (MISW4202, Arquitecturas Ágiles
de Software). Responsable: **Tibisay**.

## Propósito

Este arnés es la **experimentación automatizada** del EXP-02: ejecuta los casos
de prueba, captura la evidencia y consolida el veredicto de los criterios de
aceptación. No forma parte del sistema bajo prueba — lo observa desde afuera.

EXP-02 verifica dos propiedades de seguridad:

- **Confidencialidad** — el PAN se sustituye por un token antes de persistirse y
  no aparece en texto claro en el tráfico evaluado.
- **Integridad** — los eventos firmados con JWS se aceptan cuando son válidos y
  se rechazan, antes de aplicar cambios de estado, cuando el payload fue
  alterado.

Los criterios que el arnés debe poder demostrar:

| # | Criterio |
|---|---|
| 1 | 100% de las capturas evaluadas sin PAN en texto claro |
| 2 | 0 persistencias del PAN en MS Pagos |
| 3 | 100% de mensajes JWS válidos aceptados |
| 4 | 100% de mensajes JWS alterados rechazados antes de aplicar cambios de estado |

## Alcance

**Dentro:** casos PASS/FAIL, captura e intercepción de tráfico, detección de PAN,
recolección y sellado de evidencia, consolidación del reporte.

**Fuera:** MS Pagos y tokenización (Óscar); JWS, productor/consumidor y auditoría
(Hernán); Docker Compose, certificados/mTLS y Kafka (Donaldo). El arnés **consume**
esos componentes a través de contratos acordados; no los implementa.

## Modos de ejecución

El arnés se diseña contra contratos, no contra implementaciones, para poder
avanzar mientras los demás componentes se construyen. La variable `MODO`
selecciona contra qué corre:

| Modo | Contra qué corre | Para qué sirve |
|---|---|---|
| `simulado` | Solo dobles de prueba del arnés | Desarrollar y depurar el arnés sin dependencias |
| `mixto` | Lo que ya exista real, dobles para el resto | Integración incremental |
| `real` | Solo servicios reales | Evidencia del experimento |

### Únicamente `MODO=real` produce evidencia válida

Regla acordada con el equipo y de cumplimiento obligatorio:

> **Una corrida en modo `simulado` o `mixto` nunca constituye evidencia válida
> del experimento.**

Una corrida contra dobles demuestra que el arnés funciona, no que el sistema
cumple los criterios. Para que esto no dependa de la memoria de nadie, el modo
queda estampado en el `manifest.json` de cada corrida y el reporte de una
corrida no real se encabeza con la marca `⚠ EVIDENCIA NO VÁLIDA`.

## Estados de un caso

Definidos en [veredicto.py](veredicto.py):

| Estado | Significado |
|---|---|
| `PASS` | El caso se ejecutó y el sistema cumplió el criterio |
| `FAIL` | El caso se ejecutó y el sistema no cumplió. Hallazgo real |
| `NO_DISPONIBLE` | El caso no pudo ejecutarse. **No dice nada sobre el criterio** |
| `CONTRATO_ROTO` | El componente respondió fuera del contrato acordado |
| `ERROR_ARNES` | Falló el arnés, no el sistema |

`NO_DISPONIBLE` **nunca** se interpreta como `PASS`. Un criterio con casos sin
ejecutar se reporta como *no verificado*, jamás como cumplido: los porcentajes
se calculan solo sobre casos efectivamente evaluados y el denominador siempre
se declara.

## Catálogo de casos

[fixtures/casos.json](fixtures/casos.json) declara los 16 casos previstos del
experimento: **qué** se va a evaluar, no **cómo**. Endpoints, topics, esquemas,
tablas y puertos concretos no están ahí — dependen de contratos aún no
acordados con Donaldo, Óscar y Hernán, y vivirán en `contratos.py`.

Cada caso declara `id`, `criterio`, `descripcion`, `tipo`, `resultado_esperado`,
`responsable`, `dependencia` y `artefactos_esperados`.

| Criterio | Casos de prueba | Control |
|---|---|---|
| C1 — capturas sin PAN en claro | `CONF-01` … `CONF-04` | `CONF-99` |
| C2 — 0 persistencias del PAN | `PERS-01`, `PERS-02` | `PERS-03` |
| C3 — JWS válidos aceptados | `INTEG-01` | — |
| C4 — JWS alterados rechazados | `INTEG-02` … `INTEG-05` | — |
| habilitante (no es criterio) | `MTLS-01` … `MTLS-03` | — |

### Casos de prueba y controles

Un caso de **prueba** mide el sistema y entra en el porcentaje del criterio. Un
**control** mide el instrumento: no suma al numerador ni al denominador, pero
si no da `PASS` **invalida el criterio que protege**.

`CONF-99` existe porque C1 y C2 se demuestran con ausencias — "cero hallazgos",
"cero persistencias" — y una ausencia solo significa algo si el instrumento
sabe encontrar lo que busca. Un detector averiado reporta cero siempre.
`PERS-03` cumple el mismo papel para C2: un sistema que no guardó nada también
reporta cero PAN persistidos.

## Consolidación de resultados

[evidencia/consolidar.py](evidencia/consolidar.py) recibe los veredictos de los
casos y produce el resumen de los cuatro criterios. Reglas de agregación:

| Regla | Efecto |
|---|---|
| Denominador explícito | El porcentaje se acompaña siempre del número de casos evaluados |
| Denominador 0 | El porcentaje es `None`, nunca `0` ni `100`; el criterio queda `NO_VERIFICADO` |
| `NO_DISPONIBLE` | Fuera del numerador y del denominador; se reporta como pendiente |
| `CONTRATO_ROTO` | No es fallo de seguridad, pero impide dar el criterio por cumplido |
| `ERROR_ARNES` | Invalida el criterio: si falló el instrumento, nada de ese criterio es confiable |
| Control ≠ `PASS` | Invalida el criterio que protege, aunque las pruebas den 100 % |
| Caso sin resultado | Se cuenta como `NO_DISPONIBLE`, no desaparece del reporte |

Estados de un criterio, en orden de precedencia:

`INVALIDADO` → `NO_CUMPLE` → `NO_VERIFICADO` → `INCOMPLETO` → `CUMPLE`

`INVALIDADO` tiene precedencia porque si el instrumento no es confiable, ningún
veredicto de ese criterio lo es. Aun así el resumen **conserva todos los
conteos**: un `FAIL` real nunca desaparece del reporte porque otra cosa fallara.

## Estado actual

| Archivo | Contenido |
|---|---|
| [config.py](config.py) | Fuente central de configuración, leída del entorno |
| [veredicto.py](veredicto.py) | Vocabulario de veredictos y su agregación |
| [captura/detector_pan.py](captura/detector_pan.py) | Detección de PAN en texto y archivos, sin exponer el valor |
| [casos/test_conf99.py](casos/test_conf99.py) | Control positivo del detector |
| [fixtures/pans_sinteticos.json](fixtures/pans_sinteticos.json) | PANs sintéticos de prueba |
| [fixtures/casos.json](fixtures/casos.json) | Catálogo de los 16 casos |
| [evidencia/consolidar.py](evidencia/consolidar.py) | Consolidación en los cuatro criterios |
| [casos/test_consolidar.py](casos/test_consolidar.py) | Pruebas de la aritmética del reporte |
| [.env.example](.env.example) | Plantilla de configuración, sin secretos |
| [requirements.txt](requirements.txt) | Sin dependencias externas todavía |
| [Dockerfile](Dockerfile) | Imagen mínima sobre `python:3.11-slim` |

Pendiente, en orden: contratos, dobles de prueba, casos ejecutables, recolección
y sellado de evidencia, captura de tráfico, runner y scripts de corrida.

## Uso

```bash
cp .env.example .env                        # ajustar según el entorno local
python config.py                            # configuración resuelta

python -m unittest discover -s casos -t .   # todas las pruebas del arnés
python -m unittest casos.test_conf99        # control del detector
python -m unittest casos.test_consolidar    # aritmética del reporte

python -m captura.detector_pan <archivo>    # buscar PAN en un archivo local
python -m evidencia.consolidar <resultados.json>          # reporte en Markdown
python -m evidencia.consolidar <resultados.json> --json   # reporte en JSON
```

`config.py` no imprime credenciales: `ALMACEN_DSN` se reporta solo como
`(definido)` o `(no definido)`. El detector nunca imprime el PAN completo.

## Convenciones

- Ningún módulo lee `os.environ` ni escribe una URL por su cuenta: todo pasa por
  `config.py`.
- Ningún artefacto versionado contiene un PAN, ni siquiera sintético.
- Puertos en el rango `51xx` para no colisionar con EXP-01, que ocupa
  3000, 5000, 8000, 9090 y 15672.
- Claves, certificados, capturas `.pcap` y evidencia generada están en el
  `.gitignore` de la raíz del repositorio.
