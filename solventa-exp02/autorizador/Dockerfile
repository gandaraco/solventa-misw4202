# Contexto de construccion: solventa-exp02/ (para incluir comun/).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comun ./comun
COPY autorizador ./autorizador
RUN useradd --no-create-home servicio
USER servicio
ENV PYTHONUNBUFFERED=1 SERVICE_ID=autorizador
EXPOSE 8443
CMD ["gunicorn", "-c", "comun/gunicorn_conf.py", "autorizador.app:crear_app()"]
