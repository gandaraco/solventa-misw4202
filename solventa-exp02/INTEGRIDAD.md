# Integridad JWS y Auditoría — EXP-02

Responsable: Hernán. Este tramo implementa los criterios C3 y C4 del experimento.

## Flujo

1. MS Consentimiento construye un evento `CONSENTIMIENTO_OTORGADO` y lo firma como
   JWS compacto con `RS256` y `kid=consentimiento-v1`.
2. MS Suscripción recibe el sobre `{eventId, marcador, jws}`.
3. MS Suscripción valida estructura, algoritmo, `kid`, firma y coherencia del
   `eventId` **antes** de cambiar la suscripción de `PENDIENTE` a `ACTIVA`.
4. Servicio de Auditoría registra la aceptación o el rechazo en una bitácora
   append-only con `hashAnterior` y `hashIntegridad`.

El adaptador de transporte incluido usa HTTP dentro de `red-eventos` para que la
corrida sea determinista. El contrato JWS y el procesador no dependen del transporte;
Donaldo puede conectar Kafka al mismo punto de entrada sin cambiar la validación.

## Contratos

### Crear y publicar un consentimiento

`POST /consentimientos` en MS Consentimiento (`localhost:5102`):

```json
{"suscripcionId":"sus-1","actorId":"cliente-1","marcador":"INTEG-01"}
```

### Consumir un evento

`POST /eventos` en MS Suscripción (`localhost:5103`):

```json
{"eventId":"evt_...","marcador":"INTEG-01","jws":"cabecera.payload.firma"}
```

- `202`: firma válida y estado aplicado.
- `422`: firma ausente, truncada, inválida, clave no confiable, algoritmo no
  permitido, payload inválido o `eventId` incoherente. El estado no cambia.

`GET /suscripciones/<id>` devuelve el estado observable antes y después.

### Consultar Auditoría

`GET /registros?eventId=<id>` o `GET /registros?marcador=<marcador>` en
`localhost:5104`. Cada registro incluye resultado, motivo y hashes de la cadena.

## Material criptográfico

`scripts/generar_material.py` crea en `secretos/`, ignorado por Git:

- `consentimiento.key` y `consentimiento.pub`: par confiable de desarrollo.
- `no_confiable_jws.key` y `.pub`: par negativo para `INTEG-03`.

La clave privada solo se monta en MS Consentimiento. MS Suscripción recibe la
clave pública. No existe un valor secreto predeterminado en el repositorio.

## Ejecución

```bash
F="-f docker-compose.integridad.yml"
docker compose $F run --rm material
docker compose $F run --rm pruebas
docker compose $F up -d --build
docker compose $F run --rm verificacion-integridad
docker compose $F down
```

La suite cubre los casos `INTEG-01` a `INTEG-05`, la inmutabilidad del estado
ante rechazos, la consulta de evidencia y el encadenamiento de Auditoría.

## Integración con MS Pagos

MS Pagos usa `ClienteAuditoria` cuando `AUDITORIA_URL` está definido. Sin esa
variable conserva el registro estructurado en logs, de modo que la rama de Óscar
continúa funcionando de manera independiente. Una falla de Auditoría después de
confirmar el pago queda visible para reconciliación y no duplica la transacción.
