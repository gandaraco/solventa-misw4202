"""Firma y verificacion JWS compacta para los eventos de EXP-02.

El contrato usa RS256 y exige ``kid``. El payload se serializa de forma
canonica para que la evidencia sea reproducible. Las funciones nunca incluyen
el token ni el contenido recibido en los mensajes de error.
"""

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class JWSInvalido(ValueError):
    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


def _b64e(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def _b64d(texto):
    if not isinstance(texto, str):
        raise JWSInvalido("formato_invalido")
    try:
        return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
    except Exception as exc:
        raise JWSInvalido("formato_invalido") from exc


def _json_canonico(valor):
    return json.dumps(valor, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def firmar(payload, llave_privada_pem, kid="consentimiento-v1"):
    if not isinstance(payload, dict):
        raise TypeError("payload_debe_ser_objeto")
    cabecera = {"alg": "RS256", "kid": kid, "typ": "JWS"}
    partes = (_b64e(_json_canonico(cabecera)), _b64e(_json_canonico(payload)))
    entrada = (partes[0] + "." + partes[1]).encode("ascii")
    llave = serialization.load_pem_private_key(llave_privada_pem, password=None)
    firma = llave.sign(entrada, padding.PKCS1v15(), hashes.SHA256())
    return partes[0] + "." + partes[1] + "." + _b64e(firma)


def verificar(token, llaves_publicas):
    if not isinstance(token, str):
        raise JWSInvalido("firma_ausente")
    partes = token.split(".")
    if len(partes) != 3 or not all(partes):
        raise JWSInvalido("firma_truncada")
    try:
        cabecera = json.loads(_b64d(partes[0]))
        payload = json.loads(_b64d(partes[1]))
    except (json.JSONDecodeError, UnicodeDecodeError, JWSInvalido) as exc:
        raise JWSInvalido("formato_invalido") from exc
    if not isinstance(cabecera, dict) or cabecera.get("alg") != "RS256":
        raise JWSInvalido("algoritmo_no_permitido")
    kid = cabecera.get("kid")
    if not isinstance(kid, str) or kid not in llaves_publicas:
        raise JWSInvalido("clave_no_confiable")
    if not isinstance(payload, dict):
        raise JWSInvalido("payload_invalido")
    try:
        llave = serialization.load_pem_public_key(llaves_publicas[kid])
        llave.verify(
            _b64d(partes[2]),
            (partes[0] + "." + partes[1]).encode("ascii"),
            padding.PKCS1v15(), hashes.SHA256(),
        )
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise JWSInvalido("firma_invalida") from exc
    return payload
