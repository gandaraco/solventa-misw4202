"""Almacen append-only con hash encadenado para RegistroAuditoria (VC-004)."""

import hashlib
import json
import threading
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table,
                        Text, create_engine, select)

metadata = MetaData()
registros = Table(
    "registros_auditoria", metadata,
    Column("secuencia", Integer, primary_key=True, autoincrement=True),
    Column("registro_id", String(40), nullable=False, unique=True),
    Column("event_id", String(64), index=True),
    Column("marcador", String(64), index=True),
    Column("accion", String(64), nullable=False),
    Column("entidad_afectada", String(64), nullable=False),
    Column("entidad_id", String(64), nullable=False),
    Column("actor_id", String(64), nullable=False),
    Column("resultado", String(20), nullable=False),
    Column("motivo", String(64)),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("hash_anterior", String(64), nullable=False),
    Column("hash_integridad", String(64), nullable=False),
    Column("detalles", Text, nullable=False),
)


class AlmacenAuditoria:
    def __init__(self, url_bd):
        self._bd = create_engine(url_bd, future=True)
        metadata.create_all(self._bd)
        self._candado = threading.Lock()

    def agregar(self, fila):
        with self._candado, self._bd.begin() as cx:
            anterior = cx.execute(
                select(registros.c.hash_integridad)
                .order_by(registros.c.secuencia.desc()).limit(1)
            ).scalar_one_or_none() or "0" * 64
            base = {
                "registroId": fila["registro_id"],
                "eventId": fila.get("event_id"),
                "marcador": fila.get("marcador"),
                "accion": fila["accion"],
                "entidadAfectada": fila["entidad_afectada"],
                "entidadId": fila["entidad_id"],
                "actorId": fila["actor_id"],
                "resultado": fila["resultado"],
                "motivo": fila.get("motivo"),
                "timestamp": fila["timestamp"].isoformat(),
                "detalles": fila.get("detalles", {}),
                "hashAnterior": anterior,
            }
            digest = hashlib.sha256(json.dumps(
                base, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")).hexdigest()
            persistida = dict(fila)
            persistida["detalles"] = json.dumps(fila.get("detalles", {}), sort_keys=True)
            persistida["hash_anterior"] = anterior
            persistida["hash_integridad"] = digest
            cx.execute(registros.insert().values(**persistida))
        return {**base, "hashIntegridad": digest}

    def buscar(self, event_id=None, marcador=None):
        consulta = select(registros).order_by(registros.c.secuencia)
        if event_id:
            consulta = consulta.where(registros.c.event_id == event_id)
        if marcador:
            consulta = consulta.where(registros.c.marcador == marcador)
        with self._bd.connect() as cx:
            filas = cx.execute(consulta).mappings().all()
        return [self._a_json(f) for f in filas]

    @staticmethod
    def _a_json(fila):
        fecha = fila["timestamp"]
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        return {
            "registroId": fila["registro_id"], "eventId": fila["event_id"],
            "marcador": fila["marcador"], "accion": fila["accion"],
            "entidadAfectada": fila["entidad_afectada"],
            "entidadId": fila["entidad_id"], "actorId": fila["actor_id"],
            "resultado": fila["resultado"], "motivo": fila["motivo"],
            "timestamp": fecha.isoformat(), "hashAnterior": fila["hash_anterior"],
            "hashIntegridad": fila["hash_integridad"],
            "detalles": json.loads(fila["detalles"]),
        }
