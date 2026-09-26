# comun/gunicorn_conf.py
# Configuracion comun de gunicorn para MS Pagos y el Servicio de Tokenizacion.
import os

from comun import tls

bind = "0.0.0.0:%s" % os.getenv("PUERTO", "8443")
workers = int(os.getenv("WORKERS", "2"))
threads = int(os.getenv("HILOS", "4"))

_tls = tls.config_desde_entorno()
if _tls:
    certfile, keyfile, _ca = _tls

accesslog = "-"
# %(U)s es la ruta SIN query string. El formato por defecto registra la linea
# completa de la peticion, y un cliente que mande el PAN en la URL (?pan=...)
# lo dejaria escrito en el log aunque el servicio lo rechace.
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(B)s %(M)sms'


def ssl_context(conf, default_ssl_context_factory):
    # Reemplaza el contexto por defecto de gunicorn por el del experimento
    # (TLS 1.3 + certificado de cliente obligatorio).
    return tls.contexto_servidor(conf.certfile, conf.keyfile, _ca)
