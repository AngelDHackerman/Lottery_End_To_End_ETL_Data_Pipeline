import logging
import os
import re
import urllib.parse
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from loteria.common.aws_secrets import get_secrets
from loteria.common.config import FLAG_SIMPLE_BUCKET_WRITES, env_flag
from loteria.common.metrics import record_scraper_no_response, record_scraper_status
from loteria.common.s3_utils import check_if_sorteo_exists, upload_to_s3

# -----------------------
# Config
# -----------------------
# NOTE: no logging.basicConfig here — the JSON root handler is installed by
# configure_logging() from the entry point (lambda_handler). This module just logs to a
# named logger and lets records propagate.
logger = logging.getLogger(__name__)
buckets = get_secrets()
partitioned_bucket = buckets["partitioned"]
simple_bucket = buckets["simple"]
SCRAPE_DO_TOKEN = buckets["scrape_do_token"]
BASE_PROXY_URL = "http://api.scrape.do/"

# PR-031.1 — the proxy profile that still gets through Cloudflare.
#
# On 2026-08-20 loteria.org.gt tightened its protection and every plain request started
# coming back as `502 ROTATION_FAILED / "cannot connect target url"` after ~57 s. That
# message is misleading: it is not an unreachable host, it is scrape.do's simple HTTP
# client failing Cloudflare's browser check.
#
# All THREE parameters below are required together. Each was tested in isolation against
# the live site on 2026-08-27 and every proper subset still failed — render alone,
# super alone, render+super without a geo, render+GT without super, and plain geoCode in
# AR/BR/CL/CR/US/MX/CO/SV. Only Guatemalan residential + headless rendering answers 200.
# Do not "simplify" this by dropping one: the failure is a hard outage, not a slowdown.
#
# Cost: 25 credits per successful request (measured against RemainingMonthlyRequest),
# versus 1 before, on a 1000/month plan. extract_lottery_data() makes two proxied calls,
# so a run costs ~50. Failed requests are NOT charged — a full quota counter therefore
# proves nothing about whether the pipeline ran.
GEO_CODE = os.environ.get("SCRAPE_GEO_CODE", "GT")  # Guatemala; residential only
PROXY_RENDER = os.environ.get("SCRAPE_RENDER", "true").lower() == "true"
PROXY_SUPER = os.environ.get("SCRAPE_SUPER", "true").lower() == "true"

# Was 25 s, which sat BELOW scrape.do's own ~57 s give-up. Production therefore never saw
# the real 502 — only a requests.ReadTimeout — which is why the logs named the wrong cause
# for two weeks. 60 s lets the actual proxy error surface. A rendered success takes ~5-6 s,
# so this ceiling is only ever reached on failure, and one failure still fits inside the
# Lambda's 120 s timeout with room for the second call.
PROXY_TIMEOUT = int(os.environ.get("SCRAPE_TIMEOUT", "60"))

# The prize list moved (see extract_lottery_data). Named here so the PR-031 canary can
# assert the same literal.
PRIZE_LIST_SELECTOR = "div.lista-premios-columnas"

# A real sorteo page carries hundreds of prize lines; 10 is a floor chosen to be far below
# any legitimate page and far above the zero a wrong container yields.
MIN_PRIZE_LINES = 10
# -----------------------


def build_proxy_url(target_url: str, token: str = SCRAPE_DO_TOKEN) -> str:
    """Assemble the scrape.do request URL for ``target_url``.

    Split out of fetch_via_proxy so the parameter set can be unit-tested without a network
    call or real credentials — the combination is load-bearing (see GEO_CODE above) and a
    silent edit to it is an outage.
    """
    params = {"url": target_url, "token": token, "geoCode": GEO_CODE}
    if PROXY_RENDER:
        params["render"] = "true"
    if PROXY_SUPER:
        params["super"] = "true"

    return f"{BASE_PROXY_URL}?{urllib.parse.urlencode(params)}"


def fetch_via_proxy(target_url: str) -> requests.Response:
    """Make a request via scrape.do and leave traces in CloudWatch"""
    proxy_url = build_proxy_url(target_url)

    try:
        resp = requests.get(proxy_url, timeout=PROXY_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        # PR-031.1: emit before re-raising. Without this the timeout path produces NO
        # datapoint at all, which is precisely how the 2026-08-20 outage kept
        # ScrapeDo_Failed green while the pipeline had been dead for two weeks.
        record_scraper_no_response(type(exc).__name__)
        raise

    logger.info(
        "[PROXY] %s -> HTTP %s | Preview: %.300s",
        target_url,
        resp.status_code,
        resp.text.replace("\n", " ")[:300],
    )

    # PR-026: emit the status BEFORE the raise below. Emitting afterwards would only ever
    # record successes — the 401/402/429 responses this metric exists to catch are exactly
    # the ones that never reach a line placed after the raise. record_scraper_status()
    # swallows its own errors, so this cannot turn a good scrape into a failed one.
    record_scraper_status(resp.status_code)

    # dispara alerta temprana si el proxy falla
    if resp.status_code != 200:
        raise ValueError(f"❌ Proxy error {resp.status_code} para {target_url}")
    return resp


def extract_prize_body(soup: BeautifulSoup) -> str:
    """Return the prize list of a sorteo page as the BODY text of the raw .txt (PR-031.1).

    This used to be inline in ``extract_lottery_data`` as
    ``soup.select("div.card-body div.row")[2]`` — a positional index into someone else's
    markup. The site redesigned the page in August 2026 and that div now holds ~358
    characters of legal boilerplate ("7,920 reintegros de Q100.00 c/u…", "ESTIMADO
    PUBLICO"). Crucially there are STILL exactly three rows, so the old ``len(...) < 3``
    guard passed: the extractor would have written a prize-less raw file and the run would
    have gone green. That is a silent wrong-data failure, the worst kind this pipeline can
    have, and it is why this lives in its own tested function now.

    Page layout as of 2026-08-27:
      ``row[0]`` the ticket search box · ``row[1]`` an empty ``<div id="div_resultado">``,
      filled only when a user searches · ``row[2]`` the boilerplate above · and the prizes
      in their own ``div.lista-premios-columnas`` with ~900 ``div.premio-item`` children.

    Raises ``ValueError`` if the container is missing or does not hold prize-shaped lines.
    """
    prize_container = soup.select_one(PRIZE_LIST_SELECTOR)
    if prize_container is None:
        raise ValueError(
            f"❌ No se pudo encontrar la sección de resultados ({PRIZE_LIST_SELECTOR}). "
            "El sitio probablemente cambió su maquetado otra vez."
        )

    # The rendered markup pads each field with runs of whitespace
    # ("00068        TT        .... 800.00"). Collapsing them keeps the raw .txt
    # comparable with the 110 files already in raw/, which matters for reprocessing.
    # parser.py:89 matches on `\s+` and tolerates either form — this is about keeping the
    # archive homogeneous, not about making the parser work.
    raw_lines = prize_container.get_text(separator="\n").replace("\r", "").split("\n")
    cleaned_lines = [re.sub(r"\s{2,}", " ", line.strip()) for line in raw_lines if line.strip()]
    body_results = "\n".join(cleaned_lines)

    # Having *a* container is not proof it is the right one. A prize line looks like
    # `00046 P .... 700.00`.
    prize_lines = re.findall(r"\d+\s+\w+\s+\.+\s+[\d,]+\.?\d*", body_results)
    if len(prize_lines) < MIN_PRIZE_LINES:
        raise ValueError(
            f"❌ La sección de resultados trae {len(prize_lines)} líneas de premio "
            f"(mínimo {MIN_PRIZE_LINES}). El contenedor {PRIZE_LIST_SELECTOR} existe pero "
            "no contiene la lista de premios — revisar el maquetado del sitio."
        )

    return body_results


def extract_lottery_data(lottery_number=None, output_folder="/tmp"):  # nosec B108
    # 1️⃣ Main Page
    response = fetch_via_proxy("https://loteria.org.gt/site/award")
    soup = BeautifulSoup(response.content, "html.parser")

    # 2. Get the link of the "sorteo" (lastest one, or one in specific)
    if lottery_number:
        logger.info(f"🎯 Extracting data for lottery ID: {lottery_number}")
        sorteo_link = soup.find("a", href=lambda href: href and f"id={lottery_number}" in href)
    else:
        logger.info("🎯 Extracting data for the latest lottery.")
        sorteo_link = soup.select_one(
            "div.container a[href*='id=']"
        )  # first sorteo available, this is the best locator I could find

    if not sorteo_link:
        raise ValueError("❌ No se pudo encontrar el enlace al sorteo.")

    sorteo_url = (
        sorteo_link["href"]
        if sorteo_link["href"].startswith("http")
        else f"https://loteria.org.gt{sorteo_link['href']}"
    )
    selected_lottery_id = parse_qs(urlparse(sorteo_url).query).get("id", [None])[0]
    if not selected_lottery_id:
        raise ValueError("❌ No se pudo extraer el ID del sorteo desde la URL.")

    # 3️⃣ Página específica del sorteo
    response = fetch_via_proxy(sorteo_url)
    soup = BeautifulSoup(response.content, "html.parser")

    # 4. Extrae el encabezado
    header_div = soup.select_one("div.heading_s1.text-center")
    # Normaliza el header para eliminar líneas en blanco y exceso de espacios
    if header_div:
        raw_lines = header_div.get_text(separator="\n").replace("\r", "").split("\n")
        cleaned_lines = [line.strip() for line in raw_lines if line.strip()]
        header_text = " ".join(cleaned_lines)
    else:
        header_text = ""

    header_title = soup.find("h2").text.strip()

    # Extraer el número real del sorteo desde el encabezado
    match_sorteo = re.search(r"SORTEO.*?NO\.?\s+(\d+)", header_title, re.IGNORECASE)
    if not match_sorteo:
        raise ValueError("❌ No se pudo extraer el número del sorteo.")
    numero_sorteo_real = int(match_sorteo.group(1))

    # Limpia el título para usarlo como nombre de archivo
    clean_title = re.sub(r"\s{2,}", " ", header_title.lower()).strip()  # Colapsa espacios múltiples
    header_filename = re.sub(r"[^\w\.]+", "_", clean_title).strip(
        "_"
    )  # Reemplaza con guiones bajos

    # Extraer fecha del sorteo
    fecha_match = re.search(r"FECHA DEL SORTEO:\s*([\d/]+)", header_text)
    if fecha_match:
        fecha_sorteo_text = fecha_match.group(1)
        try:
            year = int(fecha_sorteo_text.split("/")[-1])
        except (ValueError, IndexError):
            year = "unknown"
    else:
        year = "unknown"

    # Verificar si ya fue procesado
    if check_if_sorteo_exists(partitioned_bucket, year, numero_sorteo_real):
        logger.warning(
            f"⚠️ Sorteo {numero_sorteo_real} has already been processed. Canceling extraction."
        )
        return None

    # 5. Extraer el BODY (resultados)
    body_results = extract_prize_body(soup)

    # 6. Guarda el archivo .txt localmente
    os.makedirs(output_folder, exist_ok=True)
    file_name = f"results_raw_lottery_url_id_{selected_lottery_id}_{header_filename}.txt"
    output_path = os.path.join(output_folder, file_name)

    with open(output_path, "w", encoding="utf-8") as file:
        file.write("HEADER\n")
        file.write(header_text + "\n\n")
        file.write("BODY\n")
        if not body_results.startswith("00MIL"):
            file.write("CENTENARES\n")
        file.write(body_results)

    logger.info(f"💾 Data extracted and saved to: {output_path}")

    # 7. Upload to S3
    # Hive-style path — the canonical one, and the only input the transformer reads.
    s3_key_hive = f"raw/year={year}/sorteo={numero_sorteo_real}/{file_name}"
    upload_to_s3(output_path, partitioned_bucket, s3_key_hive)

    # Simple path — fault A, being retired (PR-041.1). The roadmap's own prompt for PR-041
    # lists only the transformer's two Parquet copies; this third write is the one that is
    # easy to miss, because the extractor is not where anyone looks for a duplicated
    # *Parquet* path. Read at call time from the Lambda's environment, so flipping it is a
    # Terraform value rather than a rebuild of the zip.
    write_simple_copy = env_flag(FLAG_SIMPLE_BUCKET_WRITES)
    if write_simple_copy:
        s3_key_simple = f"raw/sorteo_{numero_sorteo_real}.txt"
        upload_to_s3(output_path, simple_bucket, s3_key_simple)

    logger.info(
        "Sorteo uploaded",
        extra={
            "sorteo": numero_sorteo_real,
            "partitioned_key": s3_key_hive,
            "wrote_simple_copy": write_simple_copy,
        },
    )
    return output_path
