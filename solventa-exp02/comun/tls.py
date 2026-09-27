# comun/tls.py
"""Contextos TLS del experimento: TLS 1.3 y certificado de cliente obligatorio.

Un unico constructor para el servidor, usado tanto por gunicorn (en el
contenedor) como por las pruebas, para que lo que se prueba sea lo que corre.
"""

import base64
import hashlib
import os
import ssl


def contexto_servidor(cert, clave, ca):
    """Servidor mTLS: sin certificado de cliente firmado por `ca`, no hay handshake."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(cert, clave)
    ctx.load_verify_locations(ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def config_desde_entorno():
    """(cert, clave, ca) si TLS esta configurado; None si el servicio corre en claro.

    Configuracion a medias es un error de despliegue, no un modo valido: se
    aborta en lugar de degradar en silencio a HTTP.
    """
    valores = (os.getenv("TLS_CERT"), os.getenv("TLS_CLAVE"), os.getenv("TLS_CA"))
    if not any(valores):
        return None
    if not all(valores):
        raise SystemExit("TLS_CERT, TLS_CLAVE y TLS_CA se configuran juntos o no se configuran")
    return valores


def huella_certificado(der):
    """Huella x5t#S256 (RFC 8705): SHA-256 del certificado DER en base64url."""
    return base64.urlsafe_b64encode(hashlib.sha256(der).digest()).rstrip(b"=").decode("ascii")


def certificado_cliente(environ):
    """(cn, huella) del certificado que presento el cliente mTLS; None si no hay.

    gunicorn expone el socket TLS en el entorno WSGI; el handshake ya valido la
    cadena contra la CA, asi que aqui solo se lee la identidad.
    """
    sock = environ.get("gunicorn.socket") or environ.get("werkzeug.socket")
    if not isinstance(sock, ssl.SSLSocket):
        return None
    der = sock.getpeercert(binary_form=True)
    if not der:
        return None
    sujeto = dict(par for rdn in sock.getpeercert().get("subject", ()) for par in rdn)
    return sujeto.get("commonName"), huella_certificado(der)
