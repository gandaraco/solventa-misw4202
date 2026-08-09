# Backlog de Arquitectura — ASRs (Architecturally Significant Requirements)

> Actividad: **Visión de Arquitectura → Backlog de Arquitectura**, curso MISW4202 Arquitecturas
> Ágiles de Software. Fuente: `MISW4202-202614-Proyecto-V2.pdf` (Caso Solventa).

## Herramienta y enlace

El backlog se documenta como **issues de GitHub** en este mismo repositorio, cada uno etiquetado
con `ASR` y con el atributo de calidad que dispara la historia. El tutor tiene acceso al repositorio
y por tanto a este backlog.

**Enlace al backlog (issues filtrados por la etiqueta `ASR`):**
https://github.com/gandaraco/solventa-misw4202/issues?q=is%3Aissue+label%3AASR

## Cómo se identificaron los ASRs

Cada ASR se derivó directamente de un escenario de atributo de calidad del caso (sección 6 del PDF:
Latencia, Escalabilidad, Disponibilidad, Seguridad, Facilidad de modificación, Facilidad de
integración), redactado como historia de usuario de arquitectura:

> Como **\<rol/stakeholder\>**, quiero **\<capacidad arquitectónica\>**, para que **\<beneficio de
> negocio\>**.

Cada issue incluye además: atributo de calidad, motivador de negocio asociado (sección 2.5),
fuente/estímulo, escenario estímulo→respuesta medible (con referencia a la sección del PDF) y una
prioridad justificada.

## Lista de los 10 ASRs

| # | Issue | Atributo de calidad | Prioridad | Resumen |
|---|-------|----------------------|-----------|---------|
| ASR-01 | [#1](https://github.com/gandaraco/solventa-misw4202/issues/1) | Latencia | Alta | Presupuesto de latencia ≤120 ms por dependencia externa (timeout duro 700 ms) en la cotización embebida. |
| ASR-02 | [#2](https://github.com/gandaraco/solventa-misw4202/issues/2) | Latencia | Alta | Degradación elegante (caché/valor por defecto) cuando un proveedor externo está lento o caído. |
| ASR-03 | [#3](https://github.com/gandaraco/solventa-misw4202/issues/3) | Escalabilidad | Alta | Absorber picos de campaña de un socio (500 → 50.000 cotizaciones/min, autoescalado ≤60 s). |
| ASR-04 | [#4](https://github.com/gandaraco/solventa-misw4202/issues/4) | Escalabilidad | Media | Ingerir ≥1.000.000 de eventos paramétricos en 10 min con contrapresión. |
| ASR-05 | [#5](https://github.com/gandaraco/solventa-misw4202/issues/5) | Disponibilidad | Alta | Continuidad ante caída de zona (RTO≤10min/RPO≤30s) y de región (RTO≤5min, failover multi-región). |
| ASR-06 | [#6](https://github.com/gandaraco/solventa-misw4202/issues/6) | Disponibilidad | Alta | Idempotencia y cero pérdida de transacciones en cobro de primas y pago de indemnizaciones (≥99,99%). |
| ASR-07 | [#7](https://github.com/gandaraco/solventa-misw4202/issues/7) | Seguridad | Alta | Cifrado en tránsito/reposo, tokenización de PII y PCI-DSS en pagos. |
| ASR-08 | [#8](https://github.com/gandaraco/solventa-misw4202/issues/8) | Seguridad | Alta | Consentimiento revocable (≤5min) y trazabilidad/explicabilidad al 100% de decisiones de suscripción. |
| ASR-09 | [#9](https://github.com/gandaraco/solventa-misw4202/issues/9) | Facilidad de modificación | Media | Añadir un ramo de seguro nuevo modificando solo componentes acotados, en ≤2 semanas-equipo. |
| ASR-10 | [#10](https://github.com/gandaraco/solventa-misw4202/issues/10) | Facilidad de integración | Alta | Dar de alta un socio embebido nuevo en ≤1 semana, sin cambios en el núcleo. |

## Cobertura frente al caso

Los 10 ASRs cubren los seis atributos de calidad del caso (§6): 2 de latencia, 2 de escalabilidad,
2 de disponibilidad, 2 de seguridad, 1 de facilidad de modificación y 1 de facilidad de integración.
Es una lista inicial, no exhaustiva — el caso lista más escenarios por atributo (§6.1–§6.6) que se
irán incorporando al backlog a medida que el equipo profundice en cada área de decisión (§8).

## Próximos pasos sugeridos

- Priorizar los ASR-01, ASR-05, ASR-07 y ASR-10 como los primeros candidatos a experimento de
  arquitectura en Flask, por ser los de mayor riesgo/mayor impacto de negocio.
- Ampliar el backlog con ASRs derivados del caso insignia (perfilamiento de vida hipotecario, §2.4),
  que tensiona los seis atributos simultáneamente.
