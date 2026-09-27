# Infraestructura e integración — EXP-02

Responsable: Donaldo. Docker Compose general, CA y certificados mTLS, mensajería
Kafka, integración del flujo mínimo y evidencia de conectividad segura
(diapositiva 9 del diseño del experimento).

## Topología

```
                     ┌──────────── red-borde (mTLS TLS 1.3 en todos los saltos) ─────────────┐
 cliente/arnés ─mTLS─► autorizador:5105  (POST /oauth/token → JWT RS256 ligado al certificado)
 cliente/arnés ─mTLS+JWT─► api-gateway:5100 ─mTLS─► ms-pagos ─mTLS─► tokenizador ─► bd-tokenizacion
                                  │                    │   (red-pci, internal)   (red-datos-pci, internal)
                                  │                    └─► bd-pagos (solo tokens) ◄── harness_lectura (127.0.0.1:5132)
                                  ├─mTLS─► ms-consentimiento ─JWS sobre Kafka (mTLS)─► ms-suscripcion
                                  └─mTLS─► ms-suscripcion        kafka:9092 (127.0.0.1:5194)
  ms-pagos, ms-suscripcion, api-gateway ─mTLS─► auditoria (append-only, hash encadenado)
                     └────────────────────────────────────────────────────────────────────────┘
```

| Táctica (VC-001/VC-005) | Cómo se materializa en EXP-02 |
|---|---|
| Identificar actores | Una CA del experimento emite un certificado por identidad; todos los servicios y Kafka exigen certificado de cliente de esa CA |
| Cifrar | TLS 1.3 obligatorio (TLS 1.2 y HTTP en claro se rechazan) en los 6 servicios Flask y en Kafka |
| Autenticar actores | Autorizador OAuth2 *client credentials* con autenticación mTLS (RFC 8705): el `client_id` es el CN del certificado |
| Autorizar actores | El API Gateway exige JWT vigente, de la audiencia correcta, con el scope de la ruta y **ligado al certificado** (`cnf.x5t#S256`) |
| Limitar la exposición | El gateway es el único punto de entrada del producto; el tokenizador y su base viven en redes `internal` y no se pueden enrutar |
| Separar entidades | `red-pci` y `red-datos-pci` emulan `ns-pagos-pci` con Network Policies |
| Manejo de log de eventos | Los rechazos del gateway se registran en Auditoría sin bloquear la respuesta (VC-003, *fire-and-forget*) |

## Componentes nuevos

| Componente | Archivos | Comportamiento |
|---|---|---|
| CA y certificados | `scripts/generar_material.py` | CA `Solventa EXP-02 CA`; certificados de servidor y cliente para `api-gateway`, `autorizador`, `ms-pagos`, `tokenizador`, `ms-consentimiento`, `ms-suscripcion`, `auditoria`, `kafka`; de cliente para `harness` y `atacante`; `no_confiable` firmado por otra CA; `certs/kafka.p12` para el broker Java; par RSA del Autorizador |
| Kafka | `kafka/server.properties`, `comun/kafka.py`, `scripts/crear_topicos.py` | KRaft de un nodo, sin listener en claro hacia la red, `ssl.client.auth=required`, TLS 1.3. Productor con `acks=all` e idempotencia; consumidor con *commit* después de procesar (al menos una vez) |
| Autorizador | `autorizador/app.py`, `comun/jwt.py` | `POST /oauth/token` (`grant_type=client_credentials`, `scope` opcional). Solo emite a clientes registrados; el JWT dura 300 s |
| API Gateway | `gateway/app.py` | mTLS → ruta conocida → JWT → scope → reenvío por mTLS con su propio certificado. No reenvía el `Authorization` ni rutas con forma de PAN |
| Captura | `captura/Dockerfile` | `tcpdump` adjunto al espacio de red de `api-gateway`, `ms-pagos` y `kafka` (perfil `captura`) |
| Verificación | `scripts/verificar_infraestructura.py`, `scripts/experimento.sh` | Corrida completa y evidencia en `evidencias/<RUN_ID>/` |

Cambios de integración en componentes existentes, sin cambiar sus contratos:
MS Suscripción extrae `procesar_sobre` para que HTTP y Kafka usen **el mismo**
procesador (verificar firma antes de cambiar estado); MS Consentimiento publica en
Kafka si `KAFKA_BOOTSTRAP` está definido; `comun/auditoria.py` habla con Auditoría
por mTLS; el access log de gunicorn redacta cualquier secuencia con forma de PAN en
la ruta; `verificar_integridad.py` acepta certificado de cliente.

## Contratos

| Servicio | Host | Red interna | Uso |
|---|---|---|---|
| api-gateway | `:5100` | `api-gateway:8443` | Entrada del producto. Rutas: `POST /pagos`, `GET /pagos`, `GET /pagos/<id>`, `POST /consentimientos`, `GET /suscripciones/<id>` |
| autorizador | `:5105` | `autorizador:8443` | `POST /oauth/token` |
| ms-pagos | `127.0.0.1:5101` | `ms-pagos:8443` | Instrumentación del arnés (contrato de Óscar) |
| ms-consentimiento | `127.0.0.1:5102` | `ms-consentimiento:8443` | Instrumentación |
| ms-suscripcion | `127.0.0.1:5103` | `ms-suscripcion:8443` | Instrumentación (`POST /eventos` sigue disponible) |
| auditoria | `127.0.0.1:5104` | `auditoria:8443` | `GET /registros?marcador=` para la evidencia |
| kafka | `127.0.0.1:5194` | `kafka:9092` | SSL con certificado de cliente |
| bd-pagos | `127.0.0.1:5132` | `bd-pagos:5432` | Usuario `harness_lectura` (C2) |

Todos los puertos exigen mTLS con TLS 1.3, salvo Postgres. Scopes del cliente
`harness`: `pagos:escribir pagos:leer consentimientos:escribir suscripciones:leer`
(se amplía con la variable `AUTORIZADOR_CLIENTES`, en JSON).

**Tópico** `solventa.consentimiento.eventos`: lleva el sobre del contrato JWS
`{eventId, marcador, jws}` sin modificarlo; la clave del mensaje es el `eventId`.
Se prefirió a `solventa.pagos.eventos` porque los eventos son de consentimiento.
Para el arnés: `TOPIC_EVENTOS=solventa.consentimiento.eventos` y
`KAFKA_BOOTSTRAP=localhost:5194`. Auditoría se mantiene por HTTP mTLS: el
rechazo debe quedar registrado antes de responder (C4).

## Ejecución (desde `solventa-exp02/`)

```bash
docker compose run --rm material     # CA, certificados y llaves (certs/, secretos/)
docker compose run --rm pruebas      # pytest
bash scripts/experimento.sh          # corrida completa desde cero, con capturas y evidencia
docker compose down -v               # bajar el stack
```

`experimento.sh` baja el stack, levanta todo, arranca las tres capturas, corre la
verificación de infraestructura y las de Óscar y Hernán contra el stack
integrado, analiza las capturas y los logs, y consolida en
`evidencias/<RUN_ID>/infraestructura/resumen.json`. Las capturas `.pcap` y los
logs quedan en la misma carpeta (ignorada por Git).

## Resultados (2026-09-26, corrida `exp02_20260927T020514Z_infra`, desde cero)

> Verificación del dueño de la infraestructura. Según la regla del arnés, la
> evidencia oficial del experimento es la corrida del arnés con `MODO=real`.

**Pruebas automatizadas: 92/92 PASS** (40 existentes + 52 nuevas en
`test_gateway.py`, `test_kafka.py` y `test_material.py`).

**Verificación de infraestructura: 77/77 PASS**

| Grupo | Casos | Resultado |
|---|---|---|
| mTLS en los 6 servicios | sin certificado, otra CA, TLS 1.2 y HTTP en claro → rechazados; certificado legítimo → atendido (control) | 30/30 |
| Kafka | sin certificado, otra CA y TLS 1.2 → rechazados; certificado legítimo lee metadatos (control) | 4/4 |
| Aislamiento PCI | `tokenizador:8443` y `bd-tokenizacion:5432` inalcanzables | 2/2 |
| API Gateway | el harness obtiene su token; sin token, llave ajena, `alg=none`, token robado con otro certificado válido, cliente no registrado, scope insuficiente, ruta al tokenizador, PAN en la ruta → rechazados; rechazo auditado | 10/10 |
| Flujo de pago por el gateway | 8 PAN sintéticos → 8 × 201 con token; respuestas sin PAN; 8 filas (control), 0 PAN en el almacén; `PAGO_REGISTRADO` en Auditoría | 8/8 |
| Integridad sobre Kafka | evento válido → `ACTIVA` y `ACEPTADO`; un atacante con certificado válido lee el sobre del tópico, altera el payload y lo reinyecta → `firma_invalida`, estado sin cambios y auditado; sobre sin firma → `firma_ausente` | 9/9 |
| Capturas (CONF-02/03) | control positivo detectado en las 3 capturas; 0 PAN en 2 186 paquetes mTLS; el segmento Postgres sin TLS muestra 17 tokens en claro y 0 PAN | 11/11 |
| Logs (CONF-04) | 1 469 líneas de 11 contenedores, 0 PAN, con un `?pan=` y un PAN en la ruta enviados a propósito | 3/3 |

Sobre el mismo stack integrado: confidencialidad de Óscar **11/11 PASS** e
integridad de Hernán **INTEG-01 a INTEG-05 PASS**. Los composes de tramo
(`docker-compose.pagos.yml`, `docker-compose.integridad.yml`) siguen pasando
sus verificaciones sin cambios.

Hallazgo corregido: el access log de gunicorn registraba la ruta, así que un
`GET /pagos/<PAN>` directo a MS Pagos dejaba el PAN en el log aunque el servicio
respondiera 404. Ahora `comun/gunicorn_conf.py` lo redacta en todos los servicios
y el gateway ni siquiera reenvía esas rutas.

## Decisiones y límites

| Decisión | Por qué |
|---|---|
| mTLS por servicio con el contexto de `comun/tls.py` en lugar de un *service mesh* | Emula el mTLS de Istio (VC-005) sin salir de Docker Compose; es lo que el arnés puede observar |
| JWT ligado al certificado (RFC 8705) | Un token robado no sirve con otro certificado, aunque también sea de la CA (caso `JWT-04`) |
| Cada servicio monta solo su certificado, su llave y la CA; la llave de firma JWS solo en MS Consentimiento y la del JWT solo en el Autorizador | Mínimo privilegio; simplificación de Vault/KMS |
| Kafka sin ACLs | Con ACLs el broker bloquearía al atacante de `KAFKA-03` y el experimento ya no mostraría que es la firma JWS la que detecta la alteración. En producción se agregan como defensa en profundidad |
| Puertos de instrumentación en `127.0.0.1` | Conservan los contratos acordados con el arnés sin exponerlos fuera del equipo; siguen exigiendo mTLS |
| Material regenerado en cada máquina | Nunca se versionan certificados, llaves ni capturas; `experimento.sh` genera el material si falta |

Pendiente: la corrida del arnés de Tibisay en `MODO=real` contra este compose.
