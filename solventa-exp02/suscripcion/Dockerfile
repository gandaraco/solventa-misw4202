FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comun ./comun
COPY suscripcion ./suscripcion
RUN useradd --no-create-home servicio
USER servicio
ENV PYTHONUNBUFFERED=1 SERVICE_ID=ms-suscripcion PORT=8080
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "suscripcion.app:crear_app()"]
