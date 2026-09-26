from datetime import timezone

from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, select

metadata = MetaData()
suscripciones = Table(
    "suscripciones", metadata,
    Column("suscripcion_id", String(64), primary_key=True),
    Column("estado", String(24), nullable=False),
    Column("ultimo_evento_id", String(64), nullable=False),
    Column("actualizada_en", DateTime(timezone=True), nullable=False),
)


class AlmacenSuscripcion:
    def __init__(self, url_bd):
        self._bd = create_engine(url_bd, future=True)
        metadata.create_all(self._bd)

    def estado(self, suscripcion_id):
        with self._bd.connect() as cx:
            fila = cx.execute(select(suscripciones).where(
                suscripciones.c.suscripcion_id == suscripcion_id
            )).mappings().first()
        return self._a_json(fila) if fila else {
            "suscripcionId": suscripcion_id, "estado": "PENDIENTE",
            "ultimoEventoId": None, "actualizadaEn": None,
        }

    def activar(self, suscripcion_id, event_id, fecha):
        with self._bd.begin() as cx:
            existente = cx.execute(select(suscripciones).where(
                suscripciones.c.suscripcion_id == suscripcion_id
            )).mappings().first()
            if existente and existente["ultimo_evento_id"] == event_id:
                return self._a_json(existente)
            valores = dict(suscripcion_id=suscripcion_id, estado="ACTIVA",
                            ultimo_evento_id=event_id, actualizada_en=fecha)
            if existente:
                cx.execute(suscripciones.update().where(
                    suscripciones.c.suscripcion_id == suscripcion_id
                ).values(**valores))
            else:
                cx.execute(suscripciones.insert().values(**valores))
        return self.estado(suscripcion_id)

    @staticmethod
    def _a_json(fila):
        fecha = fila["actualizada_en"]
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        return {"suscripcionId": fila["suscripcion_id"], "estado": fila["estado"],
                "ultimoEventoId": fila["ultimo_evento_id"],
                "actualizadaEn": fecha.isoformat()}
