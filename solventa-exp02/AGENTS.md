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
| Donaldo | Docker Compose general, CA y certificados mTLS, Kafka, API Gateway + Autorizador, captura (`docker-compose.yml`, `gateway/`, `autorizador/`, `kafka/`, `captura/`) | `feature/exp02-donaldo` | implementado y verificado sobre el stack integrado (ver Resultados y [INFRAESTRUCTURA.md](INFRAESTRUCTURA.md)) |
| Óscar | MS Pagos + Servicio de Tokenización (`pagos/`, `tokenizacion/`, `comun/`) | `feature/exp02-oscar` | implementado y verificado (ver Resultados); integrado con Auditoría en el compose general |
| Tibisay | Arnés PASS/FAIL, captura y evidencia (`harness/`) | `feature/exp02-tibisay` | catálogo de casos, detector de PAN y consolidación listos; faltan `contratos.py` y los casos ejecutables |
| Hernán | Firma y verificación JWS, productor/consumidor de Suscripción/Consentimiento, Auditoría | `feature/exp02-hernan` | implementado e integrado con el transporte Kafka |

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

### Hernán — JWS, Suscripción y Auditoría (2026-09-26)

**Suite completa: 40/40 PASS.** La corrida real de integridad reporta
`PASS INTEG-01` a `PASS INTEG-05`.

| Caso | Evidencia |
|---|---|
| INTEG-01 | Un JWS RS256 confiable activa la suscripción y genera Auditoría ACEPTADO |
| INTEG-02 | Alterar el payload invalida la firma y conserva el estado anterior |
| INTEG-03 | Un `kid` no confiable se rechaza sin aplicar cambios |
| INTEG-04 | Una firma ausente o truncada se rechaza sin aplicar cambios |
| INTEG-05 | Una firma válida no puede reutilizarse con otro payload/eventId |

Auditoría conserva registros append-only enlazados mediante `hashAnterior` y
`hashIntegridad`. El contrato completo está en [INTEGRIDAD.md](INTEGRIDAD.md).

### Donaldo — Infraestructura e integración (2026-09-26, `docker-compose.yml` desde cero)

**Pruebas: 92/92 PASS. Verificación de infraestructura (`bash scripts/experimento.sh`): 77/77 PASS.**
Sobre el mismo stack integrado, la verificación de Óscar da 11/11 y la de Hernán
INTEG-01 a INTEG-05 PASS.

| Grupo | Evidencia |
|---|---|
| mTLS | Los 6 servicios y Kafka rechazan sin certificado, con otra CA, con TLS 1.2 y en claro; el certificado legítimo es atendido (control) |
| Gateway + Autorizador | Sin token, llave ajena, `alg=none`, token robado con otro certificado válido, cliente no registrado y scope insuficiente → rechazados y auditados |
| Flujo integrado | 8 pagos por gateway → ms-pagos → tokenizador con 0 PAN en respuestas y almacén; C3/C4 con el sobre JWS viajando por Kafka y un atacante que lo altera en el tópico |
| Capturas y logs | 3 capturas con control positivo, 0 PAN en 2 186 paquetes mTLS; el segmento Postgres en claro solo lleva tokens; 1 469 líneas de log sin PAN |

Hallazgo corregido: el access log de gunicorn escribía la ruta y un `GET /pagos/<PAN>`
dejaba el PAN en el log; ahora se redacta en `comun/gunicorn_conf.py`.

## Estructura de `solventa-exp02/`
```
comun/        pan.py (misma regla de detección que el arnés), tls.py (mTLS TLS 1.3),
              ids.py, registro.py, gunicorn_conf.py
pagos/        MS Pagos: app.py, almacen.py, tokenizador.py (cliente mTLS), README.md
tokenizacion/ Servicio de Tokenización: app.py, boveda.py
pruebas/      pytest de pagos, tokenización, mTLS, integridad, gateway, Kafka y certificados
scripts/      generar_material.py (certificados y llaves de desarrollo),
              verificar_confidencialidad.py (verificación de extremo a extremo del tramo)
bd/           pagos_init.sql (usuario harness_lectura, solo lectura)
harness/      arnés de Tibisay (en su rama)
docker-compose.pagos.yml   tramo de confidencialidad, a integrar en el compose general
consentimiento/ productor de eventos firmados; suscripcion/ consumidor y estado observable
auditoria/      bitácora append-only con hash encadenado
docker-compose.integridad.yml   tramo reproducible de C3/C4
docker-compose.yml   compose general: todo el flujo con mTLS, Kafka, gateway y captura
gateway/        API Gateway (mTLS + JWT ligado al certificado, reenvío por mTLS)
autorizador/    OAuth2 client credentials con autenticación mTLS; comun/jwt.py
kafka/          server.properties del broker (TLS 1.3, certificado obligatorio); comun/kafka.py
captura/        tcpdump para los puntos de captura (perfil captura)
scripts/        verificar_infraestructura.py, experimento.sh (corrida completa), crear_topicos.py
evidencias/     salida de las corridas (ignorada por Git)
```

## Contratos acordados o propuestos
- **MS Pagos**: `POST /pagos`, `GET /pagos/<id>`, `GET /pagos?referencia=`, con mTLS en el
  host `:5101`. El detalle está en [pagos/README.md](pagos/README.md). El arnés pone su
  `marcador` en `referencia`.
- **Almacén de Pagos (C2)**: Postgres en `127.0.0.1:5132/pagos`, usuario `harness_lectura`.
- **Tokenizador**: `POST /tokens` en `tokenizador:8443`, solo desde `red-pci`; no se
  publica al host. No existe destokenización.
- **Certificados**: `certs/<identidad>.{crt,key}` para `ca`, `api-gateway`, `autorizador`,
  `ms-pagos`, `tokenizador`, `ms-consentimiento`, `ms-suscripcion`, `auditoria`, `kafka`,
  `harness`, `atacante` (CA válida, sin registro en el Autorizador) y `no_confiable`
  (otra CA); además `certs/kafka.p12`. Nombres alineados con `harness/config.py`.
- **API Gateway**: `:5100`, mTLS + `Authorization: Bearer <JWT>`. Rutas `POST|GET /pagos`,
  `GET /pagos/<id>`, `POST /consentimientos`, `GET /suscripciones/<id>`. Cabecera opcional
  `X-Marcador` para encontrar sus rechazos en Auditoría.
- **Autorizador**: `POST /oauth/token` en `:5105` con `grant_type=client_credentials`; el
  cliente se identifica con su certificado. El JWT (RS256, `kid=autorizador-v1`, 300 s)
  queda ligado al certificado por `cnf.x5t#S256`.
- **JWS**: serialización compacta, `RS256`, `kid=consentimiento-v1`. El sobre es
  `{eventId, marcador, jws}` y el `eventId` externo debe coincidir con el firmado.
- **Suscripción**: `POST /eventos` y `GET /suscripciones/<id>` en el host `:5103`.
  Solo un evento válido cambia `PENDIENTE` a `ACTIVA`; un rechazo devuelve 422.
- **Auditoría**: `POST /registros` y `GET /registros?eventId=|marcador=` en `:5104`.
  Los registros se encadenan mediante `hashAnterior` y `hashIntegridad`. MS Pagos
  usa este servicio si existe `AUDITORIA_URL` y conserva logs como respaldo.
- **Transporte**: en `docker-compose.yml` el sobre JWS viaja por Kafka (`kafka:9092`,
  host `127.0.0.1:5194`, mTLS TLS 1.3) en el tópico `solventa.consentimiento.eventos`,
  sin modificarse; MS Suscripción lo entrega al mismo `procesar_sobre` que `POST /eventos`.
  `docker-compose.integridad.yml` conserva el adaptador HTTP determinista. Auditoría
  sigue por HTTP mTLS: el rechazo queda registrado antes de responder.

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
docker compose run --rm material        # compose general: CA, certificados y llaves
docker compose run --rm pruebas
bash scripts/experimento.sh             # corrida completa desde cero, evidencia en evidencias/<RUN_ID>/
docker compose down -v

docker compose -f docker-compose.pagos.yml run --rm material   # certs/ y secretos/ de desarrollo
docker compose -f docker-compose.pagos.yml run --rm pruebas    # pytest
docker compose -f docker-compose.pagos.yml up -d --build
docker compose -f docker-compose.pagos.yml run --rm verificacion   # extremo a extremo, con el stack arriba
docker compose -f docker-compose.pagos.yml logs --no-color | docker compose -f docker-compose.pagos.yml run --rm -T verificacion python scripts/verificar_confidencialidad.py --logs

docker compose -f docker-compose.integridad.yml run --rm material
docker compose -f docker-compose.integridad.yml run --rm pruebas
docker compose -f docker-compose.integridad.yml up -d --build
docker compose -f docker-compose.integridad.yml run --rm verificacion-integridad
```
Todo va en el proyecto de Compose `name: arquitecturas-agiles`, con imágenes
`arquitecturas-agiles/<servicio>:exp02`. No uses `docker run` sueltos: agrega un
servicio con `profiles: [herramientas]` si necesitas otra herramienta.
