# AGENTS.md — Contexto de EXP-02 para asistentes de IA

Archivo para que la IA de cualquier integrante (Claude, Codex, Copilot, Cursor...)
entienda el experimento antes de tocar código. **Actualízalo en el mismo PR** cuando
cambie un contrato, un componente o una decisión.

## Proyecto
Solventa: aseguradora digital ficticia del curso MISW4202 Arquitecturas Ágiles de
Software (Uniandes). Arquitectura de **microservicios** con REST vía API Gateway y
eventos por broker. Los experimentos validan escenarios de atributos de calidad.

- `solventa-exp01/`: disponibilidad (ASR-D1/D3). Votación 2 de 3 entre réplicas de
  rating sobre RabbitMQ. Ya cerrado; solo sirve como referencia de estilo.
- `solventa-exp02/`: **este experimento**, de seguridad.

## EXP-02: confidencialidad e integridad
ASR-07 (cifrado, tokenización, PCI-DSS) y ASR-08 (consentimiento, trazabilidad).

| Criterio | Meta |
|---|---|
| C1 | 100 % de las capturas evaluadas sin PAN en texto claro |
| C2 | 0 persistencias del PAN en MS Pagos |
| C3 | 100 % de los mensajes JWS válidos aceptados |
| C4 | 100 % de los mensajes JWS alterados rechazados antes de cambiar el estado, con evidencia en Auditoría |

Tácticas: cifrar (TLS 1.3/mTLS), tokenización (limitar la exposición) y verificar
la integridad (firma JWS).

## Reglas obligatorias
1. **Solo Python + Flask.** El enunciado lo exige y el equipo lo decidió; las diapositivas
   que mencionan Spring Boot o Node.js se corrigen en el documento.
2. **Ningún PAN en ningún artefacto versionado**, ni siquiera sintético, salvo
   `harness/fixtures/pans_sinteticos.json` y los tests. Nunca registres, devuelvas ni
   persistas un PAN; tampoco lo repitas en mensajes de error.
3. **Ids y tokens no pueden contener 13 o más dígitos seguidos** (con espacios o guiones
   opcionales): el detector del arnés los reportaría como PAN. Usa `comun/ids.py`.
4. No se versionan `certs/`, `secretos/`, `.env` ni capturas `.pcap`.
5. Puertos del host en el rango `51xx` (EXP-01 usa 3000, 5000, 8000, 9090 y 15672).
6. Logs en formato `clave=valor` con `evento=...`, como en EXP-01 (`comun/registro.py`).
7. **Git:** nunca hagas commit a `main`. Rama `feature/exp02-<persona>` y PR a `main`.
8. No hay Python local garantizado: todo se corre en contenedores del proyecto de Compose
   `arquitecturas-agiles` (ver Comandos).

## Reparto y estado
| Integrante | Componente | Rama | Estado |
|---|---|---|---|
| Donaldo | Docker Compose general, CA y certificados mTLS, Kafka | — | pendiente |
| Óscar | MS Pagos + Servicio de Tokenización (`pagos/`, `tokenizacion/`, `comun/`) | `feature/exp02-oscar` | implementado y verificado (ver Resultados); falta integrar Auditoría y el compose general |
| Tibisay | Arnés PASS/FAIL, captura y evidencia (`harness/`) | `feature/exp02-tibisay` | catálogo de casos, detector de PAN y consolidación listos; faltan `contratos.py` y los casos ejecutables |
| Hernán | Firma y verificación JWS, productor/consumidor de Suscripción/Consentimiento, Auditoría | — | pendiente |

## Resultados por componente

> Son verificaciones de cada dueño **antes de integrar**. Según la regla del arnés, solo
> una corrida del arnés con `MODO=real` es evidencia válida del experimento.

### Óscar — MS Pagos + Tokenización (2026-09-25, stack `docker-compose.pagos.yml` desde cero)

**Pruebas automatizadas (`run --rm pruebas`): 32/32 PASS**, estables en 3 corridas seguidas.
| Archivo | Qué demuestra |
|---|---|
| `test_tokenizacion.py` | PAN → token `tok_...` + `ultimos4`; misma tarjeta, mismo token (también con espacios o guiones); rechaza Luhn inválido, 12 y 20 dígitos, `0000...`, tipos raros, sin repetir el valor; la bóveda no guarda el PAN en claro; logs sin PAN; 20 000 ids generados sin ninguno con forma de PAN; sin llaves no arranca |
| `test_pagos.py` | El pago devuelve y persiste solo el token; 11 PAN sintéticos → 11 filas (control) y 0 PAN en la base; campos extra con PAN no se persisten; PAN inválido o tokenizador caído → 400/503 y 0 filas; una petición inválida no llega al tokenizador; logs sin PAN |
| `test_mtls.py` | Con el contexto TLS real: certificado válido OK; sin certificado, con otra CA o con TLS 1.2 → rechazo; MS Pagos no entrega el PAN a un servidor con certificado de otra CA (mitm) |

**Extremo a extremo (`run --rm verificacion`) con Postgres, gunicorn y mTLS reales: 13/13 PASS**
| Verificación | Resultado |
|---|---|
| 8 pagos con PAN sintéticos por mTLS | 8/8 → 201, respuestas con token y sin PAN |
| Sin certificado / certificado de otra CA / TLS 1.2 | rechazados en el handshake |
| Tokenizador desde la red de borde | no alcanzable (aislado) |
| Almacén leído con `harness_lectura` | 8/8 filas de la corrida (control), 0 PAN, sin columna para PAN, el usuario no puede escribir |
| Logs de los 4 contenedores (194 líneas, incluyen `evento=pago_registrado`) | 0 PAN, incluso con un `?pan=` enviado en la URL |
| Bóveda del tokenizador (`pg_dump`, revisión manual; no está en las 13) | PAN solo cifrado (Fernet); 0 PAN en claro |

Hallazgos corregidos en el camino:
- Los ids aleatorios podían contener 13 o más dígitos seguidos, lo que daría falsos positivos del detector del arnés (ahora se descartan).
- Escanear el binario de SQLite con el patrón de PAN da falsos positivos. Para bytes crudos se busca el PAN literal; el patrón solo se aplica a texto.

## Estructura de `solventa-exp02/`
```
comun/        pan.py (misma regla de detección que el arnés), tls.py (mTLS TLS 1.3),
              ids.py, registro.py, gunicorn_conf.py
pagos/        MS Pagos: app.py, almacen.py, tokenizador.py (cliente mTLS), README.md
tokenizacion/ Servicio de Tokenización: app.py, boveda.py
pruebas/      pytest de pagos, tokenización y mTLS
scripts/      generar_material.py (certificados y llaves de desarrollo),
              verificar_confidencialidad.py (verificación de extremo a extremo del tramo)
bd/           pagos_init.sql (usuario harness_lectura, solo lectura)
harness/      arnés de Tibisay (en su rama)
docker-compose.pagos.yml   tramo de confidencialidad, a integrar en el compose general
```

## Contratos acordados o propuestos
- **MS Pagos**: `POST /pagos`, `GET /pagos/<id>`, `GET /pagos?referencia=`, con mTLS en el
  host `:5101`. El detalle está en [pagos/README.md](pagos/README.md). El arnés pone su
  `marcador` en `referencia`.
- **Almacén de Pagos (C2)**: Postgres en `127.0.0.1:5132/pagos`, usuario `harness_lectura`.
- **Tokenizador**: `POST /tokens` en `tokenizador:8443`, solo desde `red-pci`; no se
  publica al host. No existe destokenización.
- **Certificados**: `certs/{ca,ms-pagos,tokenizador,harness,no_confiable}.{crt,key}`,
  nombres alineados con `harness/config.py`.
- **Auditoría**: *pendiente (Hernán)*. MS Pagos hoy emite
  `evento=auditoria accion=PAGO_REGISTRADO entidad=Pago entidadId=... actorId=ms-pagos`
  en el log, con los campos de `RegistroAuditoria` (VC-004): entidadAfectada, entidadId,
  accion, actorId, timestamp, hashIntegridad.
- **Kafka**: *pendiente (Donaldo/Hernán)*. El arnés asume `solventa.pagos.eventos` y `solventa.auditoria`.

## Vistas de arquitectura relevantes
- **VC-004 Información**: `Pago{monto, tokenTarjeta (el PAN NO se almacena), fechaPago}`;
  `Consentimiento.hashFirma`; `Suscripcion.hashIntegridad`;
  `RegistroAuditoria` con hash encadenado.
- **VC-005 Despliegue**: `ns-pagos-pci` aislado con Network Policies, mTLS del mesh,
  Vault/KMS. En EXP-02 se emula con redes Docker `internal`, mTLS por servicio y
  llaves en archivos montados.
- **VC-003 Concurrencia**: el hilo de seguridad corre en paralelo a Voting. Ojo: el
  handshake mTLS ocurre antes del request; en paralelo solo se puede validar el JWT.

## Comandos (desde `solventa-exp02/`)
```bash
docker compose -f docker-compose.pagos.yml run --rm material   # certs/ y secretos/ de desarrollo
docker compose -f docker-compose.pagos.yml run --rm pruebas    # pytest
docker compose -f docker-compose.pagos.yml up -d --build
docker compose -f docker-compose.pagos.yml run --rm verificacion   # extremo a extremo, con el stack arriba
docker compose -f docker-compose.pagos.yml logs --no-color | docker compose -f docker-compose.pagos.yml run --rm -T verificacion python scripts/verificar_confidencialidad.py --logs
```
Todo va en el proyecto de Compose `name: arquitecturas-agiles`, con imágenes
`arquitecturas-agiles/<servicio>:exp02`. No uses `docker run` sueltos: agrega un
servicio con `profiles: [herramientas]` si necesitas otra herramienta.
