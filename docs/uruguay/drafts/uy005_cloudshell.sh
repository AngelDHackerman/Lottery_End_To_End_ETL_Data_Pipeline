#!/usr/bin/env bash
# UY-005 — ¿Se llega a www.loteria.gub.uy desde AWS? Correr en CloudShell (us-east-1).
# 4 peticiones, 1 por segundo, mismo User-Agent que el cliente de UY-001. No guarda nada fuera de /tmp.
UA="loteria-uy-research/0.1 (data-engineering portfolio; +https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline)"
U=https://www.loteria.gub.uy
D=$(mktemp -d)
echo "fecha_utc=$(date -u +%FT%TZ) region=${AWS_REGION:-?} ip_salida=$(curl -s https://checkip.amazonaws.com)"

probe() {  # nombre url
  curl -s -A "$UA" -o "$D/$1" -D "$D/$1.h" --max-time 30 \
    -w "$1 status=%{http_code} bytes=%{size_download} tipo=%{content_type} segundos=%{time_total}\n" "$2"
  grep -i -E '^(server|cf-ray|cf-mitigated|x-sucuri|x-cdn|location):' "$D/$1.h" | tr -d '\r' | sed 's/^/   cabecera: /'
  sleep 1
}

probe home      "$U/index.php"
probe resultados "$U/ver_resultados.php?vdia=23&vmes=9&vano=2026"
probe extracto  "$U/extractosweb/5deOro/extracto_5_de_oro.php?vdia=23&vmes=09&vano=2026"
probe pdf       "$U/extractosweb/20260923o.pdf"

echo "--- comprobaciones de contenido"
grep -q "MostrarExtracto('5','23','09','2026')" "$D/resultados" && echo "resultados: trae el 5 de Oro del 23/09/2026 (OK)" || echo "resultados: NO trae el bloque esperado"
grep -q "23/09/2026" "$D/extracto" && echo "extracto: trae la fecha 23/09/2026 (OK)" || echo "extracto: NO trae la fecha"
grep -i -q -E "cloudflare|just a moment|challenge|captcha|access denied" "$D"/{home,resultados,extracto} && echo "AVISO: aparece texto de desafío o bloqueo" || echo "sin texto de desafío o bloqueo"
echo "pdf sha256: $(sha256sum "$D/pdf" | cut -d' ' -f1)"
echo "esperado:   a1598f7bc8f1b99cb75e9d3e71bc4fe3b186e5bc9b14820d1e2fb72d9bb1bc26"
echo "referencia local (2026-10-04): resultados 87421 bytes (varía un poco por el bloque del día), extracto 11870, pdf 352607"
rm -rf "$D"
