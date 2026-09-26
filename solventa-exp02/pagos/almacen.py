# pagos/almacen.py
"""Persistencia de MS Pagos. Entidad Pago de la vista de informacion (VC-004).

No hay columna para el PAN: la garantia de "0 persistencias" es estructural,
no depende de que el codigo recuerde no guardarlo.
"""

import time

from sqlalchemy import (Column, DateTime, MetaData, Numeric, String, Table,
                        create_engine, select)
from sqlalchemy.exc import DBAPIError

metadata = MetaData()
pagos = Table(
    "pagos",
    metadata,
    Column("pago_id", String(40), primary_key=True),
    Column("token_tarjeta", String(40), nullable=False),
    Column("ultimos4", String(4), nullable=False),  # PCI-DSS permite conservarlos
    Column("monto", Numeric(14, 2), nullable=False),
    Column("moneda", String(3), nullable=False),
    Column("concepto", String(20), nullable=False),  # prima | indemnizacion
    Column("poliza_id", String(40)),
    Column("referencia", String(64), index=True),
    Column("estado", String(20), nullable=False),
    Column("fecha_pago", DateTime(timezone=True), nullable=False),
)


class Almacen:
    def __init__(self, url_bd, intentos_conexion=15):
        self._bd = create_engine(url_bd, pool_pre_ping=True, future=True)
        for i in range(intentos_conexion):
            try:
                metadata.create_all(self._bd)
                break
            except DBAPIError:
                # BD aun no disponible, o dos workers de gunicorn creando la
                # tabla a la vez: el reintento encuentra la tabla ya creada.
                if i == intentos_conexion - 1:
                    raise
                time.sleep(2)

    def guardar(self, fila):
        with self._bd.begin() as cx:
            cx.execute(pagos.insert().values(**fila))

    def obtener(self, pago_id):
        with self._bd.connect() as cx:
            fila = cx.execute(select(pagos).where(pagos.c.pago_id == pago_id)).mappings().first()
        return dict(fila) if fila else None

    def por_referencia(self, referencia):
        with self._bd.connect() as cx:
            filas = cx.execute(select(pagos).where(pagos.c.referencia == referencia)).mappings().all()
        return [dict(f) for f in filas]
