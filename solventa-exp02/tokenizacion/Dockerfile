# Contexto de construccion: solventa-exp02/ (para incluir comun/).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comun ./comun
COPY tokenizacion ./tokenizacion
RUN useradd --no-create-home servicio
USER servicio
ENV PYTHONUNBUFFERED=1 SERVICE_ID=tokenizador
EXPOSE 8443
CMD ["gunicorn", "-c", "comun/gunicorn_conf.py", "tokenizacion.app:crear_app()"]
