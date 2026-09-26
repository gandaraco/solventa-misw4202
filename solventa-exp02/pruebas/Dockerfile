# Imagen de herramientas: pruebas y generacion de material de desarrollo.
# El codigo se monta en /w; aqui solo se instalan dependencias (quedan en cache).
FROM python:3.11-slim
WORKDIR /w
COPY requirements.txt /tmp/requirements.txt
COPY pruebas/requirements.txt /tmp/pruebas/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/pruebas/requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1
