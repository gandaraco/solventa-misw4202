# tokenizacion/boveda.py
"""Boveda token -> PAN. Es el UNICO lugar del sistema donde el PAN persiste, y cifrado.

Dos llaves con propositos distintos:
- llave de cifrado (Fernet, AES-128-CBC + HMAC): protege el PAN en reposo; es
  lo que hace la relacion token-PAN reversible solo para quien tenga la llave.
- llave HMAC: calcula una huella del PAN para encontrar el token de una tarjeta
  ya vista sin descifrar toda la boveda. Un SHA-256 plano no sirve: el espacio
  de tarjetas es pequeno y se revierte por fuerza bruta. Con HMAC hace falta la llave.
"""

import hashlib
import hmac
import time
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from sqlalchemy import (Column, DateTime, LargeBinary, MetaData, String, Table,
                        create_engine, select)
from sqlalchemy.exc import DBAPIError, IntegrityError

from comun.ids import nuevo_id

metadata = MetaData()
tokens = Table(
    "boveda_tokens",
    metadata,
    Column("token", String(40), primary_key=True),
    Column("huella", LargeBinary(32), nullable=False, unique=True),
    Column("pan_cifrado", LargeBinary, nullable=False),
    Column("ultimos4", String(4), nullable=False),
    Column("creado", DateTime(timezone=True), nullable=False),
)


class Boveda:
    def __init__(self, url_bd, llave_cifrado, llave_hmac, intentos_conexion=15):
        self._fernet = Fernet(llave_cifrado)
        self._llave_hmac = llave_hmac
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

    def _huella(self, digitos):
        return hmac.new(self._llave_hmac, digitos.encode("ascii"), hashlib.sha256).digest()

    def tokenizar(self, digitos):
        """Devuelve (token, ultimos4, nuevo). Una misma tarjeta produce siempre el mismo token."""
        huella = self._huella(digitos)
        existente = self._buscar(huella)
        if existente:
            return existente[0], existente[1], False

        fila = {
            "token": nuevo_id("tok"),
            "huella": huella,
            "pan_cifrado": self._fernet.encrypt(digitos.encode("ascii")),
            "ultimos4": digitos[-4:],
            "creado": datetime.now(timezone.utc),
        }
        try:
            with self._bd.begin() as cx:
                cx.execute(tokens.insert().values(**fila))
        except IntegrityError:
            # Otra peticion tokenizo la misma tarjeta a la vez: gana la primera.
            existente = self._buscar(huella)
            return existente[0], existente[1], False
        return fila["token"], fila["ultimos4"], True

    def _buscar(self, huella):
        with self._bd.connect() as cx:
            return cx.execute(
                select(tokens.c.token, tokens.c.ultimos4).where(tokens.c.huella == huella)
            ).first()
