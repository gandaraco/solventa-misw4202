# MS Pagos + Servicio de Tokenización — EXP-02

Tramo de **confidencialidad** del EXP-02 (ASR-07). Responsable: **Óscar**.

El PAN (número de tarjeta) entra a MS Pagos, se envía por mTLS al Servicio de
Tokenización y se descarta. MS Pagos **solo persiste, registra en log y devuelve el token**.

```
cliente/arnés ──mTLS──► ms-pagos:8443 ──mTLS──► tokenizador:8443
  (host :5101)            │                        │
                          ▼                        ▼
                      bd-pagos                bd-tokenizacion
          (token, sin columna para el PAN)   (PAN cifrado con Fernet + huella HMAC)
```

## Contrato de MS Pagos (para el arnés y el resto del equipo)

Todas las rutas exigen **mTLS** (TLS 1.3 + certificado de cliente firmado por `certs/ca.crt`).

### `POST /pagos`
```json
{"pan": "<PAN sintético de harness/fixtures/pans_sinteticos.json>", "monto": 150000, "moneda": "COP",
 "concepto": "prima", "polizaId": "pol-1", "referencia": "EXP02-PAN-A1"}
```
| Campo | Regla |
|---|---|
| `pan` | texto; 13–19 dígitos, Luhn válido; se admiten espacios y guiones |
| `monto` | número o texto decimal > 0 |
| `concepto` | `prima` \| `indemnizacion` |
| `moneda` | opcional, 3 letras (por defecto `COP`) |
| `polizaId`, `referencia` | opcionales. **El arnés pone su `marcador` en `referencia`** para encontrar el registro (control PERS-03) |

Respuestas:
- `201`: `{"pagoId","tokenTarjeta","ultimos4","monto","moneda","concepto","polizaId","referencia","estado":"registrado","fechaPago"}`
- `400`: `{"error": "pan_invalido" | "monto_invalido" | "concepto_invalido" | "moneda_invalida"}`. Nunca repite el valor recibido.
- `503`: `{"error": "tokenizador_no_disponible"}`. Sin token no hay pago y no se persiste nada.

Los campos distintos a los anteriores se ignoran y no se persisten.

### `GET /pagos/<pagoId>` · `GET /pagos?referencia=<ref>` · `GET /salud`

### Almacén (criterio C2)
Postgres en `127.0.0.1:5132`, base `pagos`, tabla `pagos`, usuario de **solo lectura**
`harness_lectura` (clave de desarrollo `harness_lectura_dev`):

```
ALMACEN_DSN=postgresql://harness_lectura:harness_lectura_dev@localhost:5132/pagos
```

Columnas: `pago_id, token_tarjeta, ultimos4, monto, moneda, concepto, poliza_id, referencia, estado, fecha_pago`.
No existe columna para el PAN: la garantía de "0 persistencias" es estructural.

## Servicio de Tokenización

- `POST /tokens {"pan": "..."}` → `201` (token nuevo) o `200` (tarjeta ya vista): `{"token": "tok_...", "ultimos4": "1111"}`.
- La misma tarjeta produce siempre el mismo token (búsqueda por huella HMAC-SHA256).
- **No hay operación de destokenización**: en EXP-02 nadie necesita el PAN de vuelta.
- Solo es alcanzable desde MS Pagos (`red-pci` es `internal`). **No se publica al host**,
  así que los casos MTLS-01..03 del arnés deben apuntar a MS Pagos (`:5101`), no a `TOKENIZADOR_URL`.

## Decisiones de diseño

| Decisión | Por qué |
|---|---|
| Tokens e ids con `token_urlsafe` y reintento si contienen 13+ dígitos | Un id con aspecto de PAN sería un falso positivo del detector del arnés en C1/C2 |
| Huella con HMAC y no con SHA-256 plano | El espacio de PANs es pequeño: un SHA-256 se revierte por fuerza bruta |
| El access log de gunicorn registra la ruta sin query string (`%(U)s`) | Un `?pan=...` quedaría escrito en el log aunque el servicio lo rechace |
| La validación de monto y concepto va antes de tokenizar | Una petición inválida no hace viajar el PAN |
| Configuración TLS incompleta aborta el arranque | Nunca degradar en silencio a HTTP |
| Llaves de la bóveda en archivos montados (`*_ARCHIVO`) | Simplificación de Vault/KMS (VC-005) para el experimento |
| Redes Docker `internal` | Emulan `ns-pagos-pci` con Network Policies (VC-005) |

## Cómo correrlo (sin Python local, solo Docker; desde `solventa-exp02/`)

Todo corre dentro del proyecto de Docker Compose `arquitecturas-agiles`: contenedores,
redes e imágenes (`arquitecturas-agiles/*`) quedan agrupados en Docker Desktop.

```bash
F="-f docker-compose.pagos.yml"

# 1. Material de desarrollo (certs/ y secretos/, ignorados por git).
#    Los certificados definitivos los define Donaldo; los nombres coinciden con harness/config.py.
docker compose $F run --rm material

# 2. Pruebas (32): tokenización, MS Pagos y mTLS real
docker compose $F run --rm pruebas

# 3. Levantar el tramo y verificarlo de extremo a extremo (mTLS, almacén y logs)
docker compose $F up -d --build
docker compose $F run --rm verificacion
docker compose $F logs --no-color | docker compose $F run --rm -T verificacion python scripts/verificar_confidencialidad.py --logs

# 4. Bajar
docker compose $F down -v
```

## Pendiente de integración

- **Auditoría (Hernán):** por ahora el evento sale en el log como
  `evento=auditoria accion=PAGO_REGISTRADO entidad=Pago entidadId=... actorId=ms-pagos`
  (campos de `RegistroAuditoria`, VC-004). Falta acordar el canal (Kafka o HTTP).
- **Compose general (Donaldo):** integrar estos servicios, redes y certificados en el compose del experimento.
- **Punto de captura para CONF-02/03 (Donaldo y Tibisay):** el segmento ms-pagos → tokenizador va por `red-pci`.
