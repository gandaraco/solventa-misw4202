"""CA del experimento, certificados por identidad y keystore de Kafka."""

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import generar_material

SERVICIOS = ["api-gateway", "autorizador", "ms-pagos", "tokenizador", "ms-consentimiento",
             "ms-suscripcion", "auditoria", "kafka"]


@pytest.fixture(scope="module")
def raiz(tmp_path_factory):
    d = tmp_path_factory.mktemp("material")
    generar_material.generar_certs(d / "certs")
    generar_material.generar_secretos(d / "secretos")
    generar_material.generar_keystore_kafka(d / "certs", d / "secretos")
    return d


def _cert(raiz, nombre):
    return x509.load_pem_x509_certificate((raiz / "certs" / (nombre + ".crt")).read_bytes())


def _cn(cert):
    return cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value


@pytest.mark.parametrize("nombre", SERVICIOS)
def test_servicio_emitido_por_la_ca_con_su_nombre_dns(raiz, nombre):
    cert, ca = _cert(raiz, nombre), _cert(raiz, "ca")
    cert.verify_directly_issued_by(ca)
    assert _cn(cert) == nombre
    dns = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert nombre in dns.get_values_for_type(x509.DNSName)
    usos = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    # Todo servicio es servidor y tambien cliente mTLS de otro servicio.
    assert ExtendedKeyUsageOID.SERVER_AUTH in usos and ExtendedKeyUsageOID.CLIENT_AUTH in usos


@pytest.mark.parametrize("nombre", ["harness", "atacante"])
def test_clientes_solo_autenticacion_de_cliente(raiz, nombre):
    cert = _cert(raiz, nombre)
    cert.verify_directly_issued_by(_cert(raiz, "ca"))
    usos = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert list(usos) == [ExtendedKeyUsageOID.CLIENT_AUTH]


def test_no_confiable_no_lo_emite_la_ca(raiz):
    with pytest.raises(Exception):
        _cert(raiz, "no_confiable").verify_directly_issued_by(_cert(raiz, "ca"))


def test_llave_corresponde_al_certificado(raiz):
    for nombre in SERVICIOS + ["harness", "atacante"]:
        llave = serialization.load_pem_private_key(
            (raiz / "certs" / (nombre + ".key")).read_bytes(), None)
        assert llave.public_key() == _cert(raiz, nombre).public_key()


def test_keystore_de_kafka_abre_con_la_clave_de_secretos(raiz):
    propiedades = dict(linea.split("=", 1) for linea in
                       (raiz / "secretos" / "kafka_ssl.properties").read_text().splitlines())
    assert propiedades["ssl.keystore.password"] == propiedades["ssl.key.password"]
    llave, cert, cadena = pkcs12.load_key_and_certificates(
        (raiz / "certs" / "kafka.p12").read_bytes(), propiedades["ssl.keystore.password"].encode())
    assert _cn(cert) == "kafka" and llave.public_key() == cert.public_key()
    assert cadena == [_cert(raiz, "ca")]
    with pytest.raises(ValueError):
        pkcs12.load_key_and_certificates((raiz / "certs" / "kafka.p12").read_bytes(), b"otra")


def test_par_jwt_del_autorizador(raiz):
    privada = serialization.load_pem_private_key(
        (raiz / "secretos" / "autorizador_jwt.key").read_bytes(), None)
    publica = serialization.load_pem_public_key((raiz / "secretos" / "autorizador_jwt.pub").read_bytes())
    assert privada.public_key() == publica
