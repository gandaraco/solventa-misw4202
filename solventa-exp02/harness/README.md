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

## Estado actual

Esqueleto inicial. Implementado:

| Archivo | Contenido |
|---|---|
| [config.py](config.py) | Fuente central de configuración, leída del entorno |
| [veredicto.py](veredicto.py) | Vocabulario de veredictos y su agregación |
| [.env.example](.env.example) | Plantilla de configuración, sin secretos |
| [requirements.txt](requirements.txt) | Sin dependencias externas todavía |
| [Dockerfile](Dockerfile) | Imagen mínima sobre `python:3.11-slim` |

Pendiente, en orden: contratos, detector de PAN y su control positivo, dobles de
prueba, casos, recolección de evidencia, captura de tráfico y scripts de corrida.

## Uso

```bash
cp .env.example .env     # ajustar según el entorno local
python config.py         # imprime la configuración resuelta
```

`config.py` no imprime credenciales: `ALMACEN_DSN` se reporta solo como
`(definido)` o `(no definido)`.

## Convenciones

- Ningún módulo lee `os.environ` ni escribe una URL por su cuenta: todo pasa por
  `config.py`.
- Ningún artefacto versionado contiene un PAN, ni siquiera sintético.
- Puertos en el rango `51xx` para no colisionar con EXP-01, que ocupa
  3000, 5000, 8000, 9090 y 15672.
- Claves, certificados, capturas `.pcap` y evidencia generada están en el
  `.gitignore` de la raíz del repositorio.
