import logging
import os
import re
import urllib.parse
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from loteria.common.aws_secrets import get_secrets
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
GEO_CODE = "MX"  # geo-targeting Mexico
# -----------------------


def fetch_via_proxy(target_url: str) -> requests.Response:
    """Make a request via scrape.do and leave traces in CloudWatch"""
    encoded = urllib.parse.quote(target_url, safe="")
    proxy_url = (
        f"{BASE_PROXY_URL}" f"?url={encoded}" f"&token={SCRAPE_DO_TOKEN}" f"&geoCode={GEO_CODE}"
    )

    resp = requests.get(proxy_url, timeout=25)
    logger.info(
        "[PROXY] %s -> HTTP %s | Preview: %.300s",
        target_url,
        resp.status_code,
        resp.text.replace("\n", " ")[:300],
    )

    # dispara alerta temprana si el proxy falla
    if resp.status_code != 200:
        raise ValueError(f"❌ Proxy error {resp.status_code} para {target_url}")
    return resp


def extract_lottery_data(lottery_number=None, output_folder="/tmp"):
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
    # Basado en estructura observada: el tercer div.row dentro de .card-body
    result_divs = soup.select("div.card-body div.row")
    if len(result_divs) < 3:
        raise ValueError("❌ No se pudo encontrar la sección de resultados.")

    raw_lines = result_divs[2].get_text(separator="\n").replace("\r", "").split("\n")
    cleaned_lines = [line.strip() for line in raw_lines if line.strip()]
    body_results = "\n".join(cleaned_lines)

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

    # 7. Dual upload to S3
    # Hive-style path
    s3_key_hive = f"raw/year={year}/sorteo={numero_sorteo_real}/{file_name}"
    upload_to_s3(output_path, partitioned_bucket, s3_key_hive)

    # Simple path
    s3_key_simple = f"raw/sorteo_{numero_sorteo_real}.txt"
    upload_to_s3(output_path, simple_bucket, s3_key_simple)

    logger.info(f"✅ Sorteo {numero_sorteo_real} subido a ambos buckets.")
    return output_path
