# comun/gunicorn_conf.py
# Configuracion comun de gunicorn para todos los servicios Flask de EXP-02.
import os

from gunicorn.glogging import Logger

from comun import tls
from comun.pan import PATRON_PAN

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


class LoggerSinPan(Logger):
    # La ruta tambien la controla el cliente (GET /pagos/<lo que sea>): toda
    # secuencia con forma de PAN se redacta antes de escribir el access log.
    def atoms(self, resp, req, environ, request_time):
        atomos = super().atoms(resp, req, environ, request_time)
        atomos["U"] = PATRON_PAN.sub("[redactado]", atomos["U"])
        return atomos


logger_class = LoggerSinPan


def ssl_context(conf, default_ssl_context_factory):
    # Reemplaza el contexto por defecto de gunicorn por el del experimento
    # (TLS 1.3 + certificado de cliente obligatorio).
    return tls.contexto_servidor(conf.certfile, conf.keyfile, _ca)
