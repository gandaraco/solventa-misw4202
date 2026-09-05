# -*- coding: utf-8 -*-
"""Resume el histograma del Validador. Uso: python medir.py [etiqueta]"""
import re
import sys
import urllib.request

URL = "http://localhost:8000/metrics"
PRESUPUESTO = 0.1  # ASR-D1


def pct(bs, total, q):
    objetivo = total * q
    prev_le = prev_c = 0.0
    for le, c in bs:
        if c >= objetivo:
            if le == float("inf"):
                return prev_le * 1000
            if c > prev_c:
                return (prev_le + (le - prev_le) * ((objetivo - prev_c) / (c - prev_c))) * 1000
            return le * 1000
        prev_le, prev_c = le, c
    return float("nan")


txt = urllib.request.urlopen(URL).read().decode()
buckets, counts, sums, contadores = {}, {}, {}, []
for line in txt.splitlines():
    m = re.match(r'asr_d1_latencia_deteccion_segundos_bucket\{cierre="(\w+)",le="([^"]+)"\} ([\d.e+]+)', line)
    if m:
        buckets.setdefault(m.group(1), []).append((float(m.group(2)), float(m.group(3))))
    m = re.match(r'asr_d1_latencia_deteccion_segundos_count\{cierre="(\w+)"\} ([\d.e+]+)', line)
    if m:
        counts[m.group(1)] = float(m.group(2))
    m = re.match(r'asr_d1_latencia_deteccion_segundos_sum\{cierre="(\w+)"\} ([\d.e+]+)', line)
    if m:
        sums[m.group(1)] = float(m.group(2))
    if line.startswith(("asr_d1_veredictos_total{", "asr_d1_divergencias_total{",
                        "asr_d1_respuestas_tardias_total{")):
        contadores.append(line)

etiqueta = sys.argv[1] if len(sys.argv) > 1 else "corrida"
print("=" * 96)
print("CONDICION: %s" % etiqueta)
print("=" * 96)
if not counts:
    print("Sin veredictos registrados todavia.")
    sys.exit(0)

print("%-9s %7s %9s %8s %8s %8s %8s   %s" %
      ("cierre", "n", "media ms", "p50", "p95", "p99", "max", "dentro de 100 ms"))
print("-" * 96)
total_n = total_dentro = 0
for cierre in sorted(counts):
    bs = sorted(buckets[cierre])
    n = counts[cierre]
    dentro = next((c for le, c in bs if le == PRESUPUESTO), 0.0)
    total_n += n
    total_dentro += dentro
    mx = pct(bs, n, 1.0)
    print("%-9s %7d %9.1f %8.1f %8.1f %8.1f %8.1f   %6.2f %%" %
          (cierre, n, sums[cierre] / n * 1000, pct(bs, n, .50), pct(bs, n, .95),
           pct(bs, n, .99), mx, dentro / n * 100))
print("-" * 96)
cumple = total_dentro / total_n * 100
print("ASR-D1 (deteccion <= 100 ms): %.2f %% de %d detecciones   ->   %s"
      % (cumple, total_n, "CUMPLE" if cumple >= 95 else "NO CUMPLE en p95"))
if "quorum" in counts:
    bs = sorted(buckets["quorum"])
    print("\nCalibracion del timeout: p99 de cierre=quorum = %.1f ms" % pct(bs, counts["quorum"], .99))
    print("  -> el timeout debe quedar por encima de ese valor para no cortar replicas lentas pero vivas.")
print("\nContadores:")
for c in contadores:
    print("  " + c)
