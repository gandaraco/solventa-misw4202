# -*- coding: utf-8 -*-
"""Mide SOLO una ventana de tiempo consultando Prometheus, sin reiniciar nada.

Uso:  python medir_ventana.py <ventana> [etiqueta]
Ej:   python medir_ventana.py 2m "B - replica divergente"

Prometheus guarda el historial, asi que basta con acotar la ventana a la corrida
que acaba de terminar. Evita el problema de que el histograma sea acumulativo.
"""
import json
import sys
import urllib.parse
import urllib.request

PROM = "http://localhost:9090/api/v1/query"
METRICA = "asr_d1_latencia_deteccion_segundos"


def q(expr):
    url = PROM + "?" + urllib.parse.urlencode({"query": expr})
    data = json.loads(urllib.request.urlopen(url).read().decode())
    if data.get("status") != "success":
        raise SystemExit("Prometheus respondio: %s" % data)
    return data["data"]["result"]


def valores(expr, clave="cierre"):
    return {r["metric"].get(clave, "-"): float(r["value"][1]) for r in q(expr)}


ventana = sys.argv[1] if len(sys.argv) > 1 else "2m"
etiqueta = sys.argv[2] if len(sys.argv) > 2 else "corrida"

n = valores("sum by (cierre) (increase(%s_count[%s]))" % (METRICA, ventana))
if not n or sum(n.values()) < 1:
    raise SystemExit("Sin datos en la ventana %s. Prometheus scrapea cada 2 s; "
                     "verifica que la corrida haya ocurrido dentro de ese lapso." % ventana)

suma = valores("sum by (cierre) (increase(%s_sum[%s]))" % (METRICA, ventana))
dentro = valores('sum by (cierre) (increase(%s_bucket{le="0.1"}[%s]))' % (METRICA, ventana))
pcts = {}
for p in (0.50, 0.95, 0.99):
    pcts[p] = valores("histogram_quantile(%.2f, sum by (le, cierre) (increase(%s_bucket[%s])))"
                      % (p, METRICA, ventana))

print("=" * 92)
print("CONDICION: %s        ventana: ultimos %s" % (etiqueta, ventana))
print("=" * 92)
print("%-9s %9s %9s %8s %8s %8s   %s" %
      ("cierre", "n", "media ms", "p50", "p95", "p99", "dentro de 100 ms"))
print("-" * 92)
tot_n = tot_dentro = 0.0
for c in sorted(n):
    cn = n[c]
    tot_n += cn
    tot_dentro += dentro.get(c, 0.0)
    print("%-9s %9.0f %9.1f %8.1f %8.1f %8.1f   %6.2f %%" %
          (c, cn, suma.get(c, 0) / cn * 1000, pcts[0.50].get(c, 0) * 1000,
           pcts[0.95].get(c, 0) * 1000, pcts[0.99].get(c, 0) * 1000,
           dentro.get(c, 0.0) / cn * 100))
print("-" * 92)
cumple = tot_dentro / tot_n * 100
print("ASR-D1 (deteccion <= 100 ms): %.2f %% de %.0f detecciones   ->   %s"
      % (cumple, tot_n, "CUMPLE" if cumple >= 95 else "NO CUMPLE en p95"))
if "quorum" in pcts[0.99]:
    print("\nCalibracion del timeout: p99 de cierre=quorum = %.1f ms"
          % (pcts[0.99]["quorum"] * 1000))

for nombre, etiq in (("asr_d1_divergencias_total", "instancia"),
                     ("asr_d1_respuestas_tardias_total", "instancia")):
    v = valores("sum by (%s) (increase(%s[%s]))" % (etiq, nombre, ventana), etiq)
    if v:
        print("\n%s en la ventana:" % nombre)
        for k, x in sorted(v.items()):
            print("  %-12s %.0f" % (k, x))
