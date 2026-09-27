# scripts/generar_material.py
"""Genera la CA del experimento, los certificados mTLS y las llaves de DESARROLLO.

Una sola CA ("Solventa EXP-02 CA") emite un certificado por identidad; es la
Entidad Certificadora de la vista funcional (VC-001). Los nombres de archivo
coinciden con los que espera el arnes (harness/config.py): certs/ca.crt,
certs/harness.crt, certs/no_confiable.crt...

Identidades:
- servicios (certificado de servidor y de cliente): api-gateway, autorizador,
  ms-pagos, tokenizador, ms-consentimiento, ms-suscripcion, auditoria, kafka.
- clientes: harness (legitimo) y atacante (firmado por la CA del experimento,
  pero no registrado en el Autorizador: sirve para probar el robo de un JWT).
- no_confiable: firmado por OTRA CA (caso negativo MTLS-02).

Kafka es Java y no lee llaves PEM sueltas: su certificado se empaqueta ademas en
certs/kafka.p12, con una clave aleatoria que queda en secretos/kafka_ssl.properties.

Uso (sin Python local, desde solventa-exp02/):
    docker compose run --rm material

Salida (ignorada por git): certs/ y secretos/.
"""

import base64
import datetime
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Identidad -> nombres DNS que puede presentar como servidor.
SERVICIOS = {
    "api-gateway": ["api-gateway", "localhost"],
    "autorizador": ["autorizador", "localhost"],
    "ms-pagos": ["ms-pagos", "localhost"],
    "tokenizador": ["tokenizador", "localhost"],
    "ms-consentimiento": ["ms-consentimiento", "localhost"],
    "ms-suscripcion": ["ms-suscripcion", "localhost"],
    "auditoria": ["auditoria", "localhost"],
    "kafka": ["kafka", "localhost"],
    "harness": [],
    "atacante": [],
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
    return ca_cert


def generar_keystore_kafka(dir_certs, dir_secretos):
    """certs/kafka.p12 a partir de kafka.crt/.key, y su clave en secretos/."""
    dir_certs, dir_secretos = Path(dir_certs), Path(dir_secretos)
    dir_secretos.mkdir(parents=True, exist_ok=True)
    cert = x509.load_pem_x509_certificate((dir_certs / "kafka.crt").read_bytes())
    llave = serialization.load_pem_private_key((dir_certs / "kafka.key").read_bytes(), None)
    ca = x509.load_pem_x509_certificate((dir_certs / "ca.crt").read_bytes())
    clave = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii")
    cifrado = (serialization.PrivateFormat.PKCS12.encryption_builder()
               .kdf_rounds(50000)
               .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC)
               .hmac_hash(hashes.SHA256())
               .build(clave.encode("ascii")))
    ruta = dir_certs / "kafka.p12"
    ruta.write_bytes(pkcs12.serialize_key_and_certificates(b"kafka", llave, cert, [ca], cifrado))
    os.chmod(ruta, 0o644)
    # Se concatena al server.properties del broker al arrancar (kafka/server.properties).
    (dir_secretos / "kafka_ssl.properties").write_text(
        "ssl.keystore.password=%s\nssl.key.password=%s\n" % (clave, clave), encoding="ascii")
    os.chmod(dir_secretos / "kafka_ssl.properties", 0o644)


def generar_secretos(directorio):
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    # Fernet exige 32 bytes en base64 url-safe.
    (directorio / "llave_cifrado").write_bytes(base64.urlsafe_b64encode(os.urandom(32)))
    (directorio / "llave_hmac").write_bytes(base64.urlsafe_b64encode(os.urandom(32)))
    # Par JWS de desarrollo. El productor monta la privada y el consumidor
    # unicamente la publica. El segundo par permite INTEG-03. El par del
    # Autorizador firma los JWT de acceso; el API Gateway solo recibe la publica.
    for nombre in ("consentimiento", "no_confiable_jws", "autorizador_jwt"):
        llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        (directorio / (nombre + ".key")).write_bytes(llave.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        (directorio / (nombre + ".pub")).write_bytes(llave.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo))
    for f in directorio.iterdir():
        os.chmod(f, 0o644)


if __name__ == "__main__":
    raiz = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    generar_certs(raiz / "certs")
    generar_secretos(raiz / "secretos")
    generar_keystore_kafka(raiz / "certs", raiz / "secretos")
    print("Material de desarrollo en %s/certs y %s/secretos" % (raiz, raiz))
