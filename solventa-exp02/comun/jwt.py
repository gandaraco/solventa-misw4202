"""JWT de acceso (OAuth2 client credentials) emitidos por el Autorizador.

Un JWT es un JWS con claims: se reutiliza comun/jws.py (RS256 y ``kid``
obligatorio). El token queda ligado al certificado mTLS del cliente mediante
``cnf.x5t#S256`` (RFC 8705): un token robado no sirve con otro certificado.
"""

import time

from comun import jws


class JWTInvalido(ValueError):
    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


def emitir(sujeto, scopes, huella, llave_privada_pem, kid, emisor, audiencia,
           duracion_s=300, ahora=None):
    ahora = int(ahora if ahora is not None else time.time())
    claims = {
        "iss": emisor, "sub": sujeto, "aud": audiencia,
        "iat": ahora, "nbf": ahora, "exp": ahora + duracion_s,
        "scope": " ".join(sorted(scopes)),
        "cnf": {"x5t#S256": huella},
    }
    return jws.firmar(claims, llave_privada_pem, kid, typ="JWT")


def validar(token, llaves_publicas, emisor, audiencia, huella, ahora=None, holgura_s=30):
    """Claims del token si es valido para este certificado; si no, JWTInvalido."""
    try:
        claims = jws.verificar(token, llaves_publicas)
    except jws.JWSInvalido as exc:
        raise JWTInvalido(exc.motivo) from None
    ahora = ahora if ahora is not None else time.time()
    if claims.get("iss") != emisor:
        raise JWTInvalido("emisor_invalido")
    if claims.get("aud") != audiencia:
        raise JWTInvalido("audiencia_invalida")
    exp, nbf = claims.get("exp"), claims.get("nbf", 0)
    if not isinstance(exp, (int, float)) or not isinstance(nbf, (int, float)):
        raise JWTInvalido("vigencia_invalida")
    if ahora > exp + holgura_s:
        raise JWTInvalido("token_expirado")
    if ahora + holgura_s < nbf:
        raise JWTInvalido("token_aun_no_valido")
    cnf = claims.get("cnf")
    if not isinstance(cnf, dict) or cnf.get("x5t#S256") != huella:
        raise JWTInvalido("certificado_no_coincide")
    return claims


def scopes(claims):
    valor = claims.get("scope")
    return set(valor.split()) if isinstance(valor, str) else set()
