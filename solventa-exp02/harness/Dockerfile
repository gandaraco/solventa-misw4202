# Arnes de experimentacion de EXP-02.
# Sigue el patron de imagen de EXP-01 (python:3.11-slim, requirements antes que
# el codigo para aprovechar la cache de capas). No hereda nada de su logica.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /arnes

# Capa de dependencias primero: cambiar el codigo no invalida el pip install.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El esqueleto todavia no tiene runner: por ahora la imagen imprime la
# configuracion resuelta, que es lo que permite verificar el cableado del
# entorno (endpoints, rutas de certificados, modo) antes de que existan casos.
CMD ["python", "config.py"]
