# scripts/generar_material.py
"""Genera certificados mTLS y llaves de la boveda para DESARROLLO.

Donaldo es el dueno de los certificados definitivos del experimento; este
script existe para que MS Pagos y la tokenizacion se puedan levantar y probar
antes. Los nombres de archivo coinciden con los que espera el arnes
(harness/config.py): certs/ca.crt, certs/harness.crt, certs/no_confiable.crt...

Uso (sin Python local, desde solventa-exp02/):
    docker run --rm -v "$PWD:/w" -w /w python:3.11-slim \
        sh -c "pip install -q cryptography && python scripts/generar_material.py"

Salida (ignorada por git): certs/ y secretos/.
"""

import base64
import datetime
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Identidad -> nombres DNS que puede presentar como servidor.
SERVICIOS = {
    "ms-pagos": ["ms-pagos", "localhost"],
    "tokenizador": ["tokenizador", "localhost"],
    "harness": [],
}


def _nombre(cn):
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Solventa EXP-02"),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _llave():
    return ec.generate_private_key(ec.SECP256R1())


def crear_ca(cn):
    llave = _llave()
    ahora = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_nombre(cn)).issuer_name(_nombre(cn))
        .public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(minutes=5))
        .not_valid_after(ahora + datetime.timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .sign(llave, hashes.SHA256())
    )
    return cert, llave


def crear_hoja(cn, dns, ca_cert, ca_llave):
    llave = _llave()
    ahora = datetime.datetime.now(datetime.timezone.utc)
    usos = [ExtendedKeyUsageOID.CLIENT_AUTH] + ([ExtendedKeyUsageOID.SERVER_AUTH] if dns else [])
    b = (
        x509.CertificateBuilder()
        .subject_name(_nombre(cn)).issuer_name(ca_cert.subject)
        .public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(minutes=5))
        .not_valid_after(ahora + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage(usos), critical=False)
    )
    if dns:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(d) for d in dns]), critical=False)
    return b.sign(ca_llave, hashes.SHA256()), llave


def _escribir(directorio, nombre, cert, llave):
    (directorio / (nombre + ".crt")).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ruta_llave = directorio / (nombre + ".key")
    ruta_llave.write_bytes(llave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    # Legible por el usuario sin privilegios de los contenedores (volumen de
    # solo lectura, entorno de desarrollo). En produccion esto lo resuelve Vault.
    os.chmod(ruta_llave, 0o644)


def generar_certs(directorio):
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    ca_cert, ca_llave = crear_ca("Solventa EXP-02 CA")
    _escribir(directorio, "ca", ca_cert, ca_llave)
    for cn, dns in SERVICIOS.items():
        _escribir(directorio, cn, *crear_hoja(cn, dns, ca_cert, ca_llave))
    # Par firmado por OTRA CA: caso negativo MTLS-02 del arnes.
    otra_cert, otra_llave = crear_ca("CA no confiable")
    _escribir(directorio, "no_confiable", *crear_hoja("impostor", [], otra_cert, otra_llave))


def generar_secretos(directorio):
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    # Fernet exige 32 bytes en base64 url-safe.
    (directorio / "llave_cifrado").write_bytes(base64.urlsafe_b64encode(os.urandom(32)))
    (directorio / "llave_hmac").write_bytes(base64.urlsafe_b64encode(os.urandom(32)))
    for f in directorio.iterdir():
        os.chmod(f, 0o644)


if __name__ == "__main__":
    raiz = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    generar_certs(raiz / "certs")
    generar_secretos(raiz / "secretos")
    print("Material de desarrollo en %s/certs y %s/secretos" % (raiz, raiz))
