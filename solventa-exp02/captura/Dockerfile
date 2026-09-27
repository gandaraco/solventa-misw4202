# Punto de captura de trafico (conector de intercepcion, no es parte del producto).
# Se adjunta al espacio de red de un servicio (network_mode: service:<x>) y
# escribe un .pcap por segmento en evidencias/, que analiza
# scripts/verificar_infraestructura.py --capturas.
FROM alpine:3.20
RUN apk add --no-cache tcpdump
ENTRYPOINT ["tcpdump", "-Z", "root", "-i", "any", "-U", "-n", "-s", "0"]
