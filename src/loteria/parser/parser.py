import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)


def split_header_body(content_lines):
    """
    Splits the content of a file into HEADER and BODY sections.
    Args:
        content_lines (list): List of lines in the file.
    Returns:
        tuple: HEADER and BODY sections as lists of strings.
    """
    # Limpia las líneas antes de buscar
    content_cleaned = [line.strip() for line in content_lines if line.strip()]

    try:
        header_start = content_cleaned.index("HEADER")
        body_start = content_cleaned.index("BODY")
    except ValueError:
        logger.error("Content does not contain 'HEADER' or 'BODY' sections")
        raise ValueError("The file does not contain expected HEADER or BODY sections.") from None

    header = content_cleaned[
        header_start + 1 : body_start
    ]  # splits the information for header dataset
    body = content_cleaned[body_start + 1 :]  # splits the information for body dataset

    return header, body


def process_header(header):
    """
    Processes the HEADER section and extracts relevant fields.
    Args:
        header (list): List of lines in the HEADER section.
    Returns:
        dict: Extracted data from the HEADER section.
    """
    # Regular expressions for extract specific information in header
    try:
        numero_sorteo = re.search(r"NO. (\d+)", header[0]).group(1)
        tipo_sorteo = re.search(r"SORTEO (\w+)", header[0], re.IGNORECASE).group(1)
        fecha_sorteo = re.search(r"FECHA DEL SORTEO: ([\d/]+)", " ".join(header)).group(1)
        fecha_caducidad = re.search(r"FECHA DE CADUCIDAD: ([\d/]+)", " ".join(header)).group(1)
        premios = re.search(
            r"PRIMER PREMIO (\d+) \|\|\| SEGUNDO PREMIO (\d+) \|\|\| TERCER PREMIO (\d+)",
            " ".join(header),
        )
        primer_premio, segundo_premio, tercer_premio = premios.groups()
        reintegros = re.search(r"REINTEGROS ([\d, ]+)", " ".join(header)).group(1).replace(" ", "")
    except AttributeError as e:
        logger.error("An error occurred while processing the HEADER")
        raise ValueError("The HEADER does not contain the expected format.") from e

    return {
        "numero_sorteo": int(numero_sorteo),
        "tipo_sorteo": tipo_sorteo,
        "fecha_sorteo": fecha_sorteo,
        "fecha_caducidad": fecha_caducidad,
        "primer_premio": int(primer_premio),
        "segundo_premio": int(segundo_premio),
        "tercer_premio": int(tercer_premio),
        "reintegros": reintegros,
    }


# ==========================================================================================
# Reject vocabulary (PR-044.1, fault E)
# ==========================================================================================
# Every body line the parser does not turn into data gets one of these codes. The codes are
# a CLOSED set on purpose: PR-044.2 registers the quarantine as an Athena table, and
# `SELECT reason, count(*)` is worthless over free text.
#
# **These three were measured, not invented.** Running this parser over the whole archived
# corpus on 2026-09-27 — 118 draws, 145,680 body lines — produced:
#
#     premios                    124,447   85.42%
#     vendedor / no vendido       11,768    8.08%
#     REJECT_SECTION_HEADER        9,464    6.4964%   <- expected, structural
#     REJECT_ORPHAN_VENDOR_LINE        0    0%
#     REJECT_UNRECOGNISED              1    0.00069%  <- '00CERO', sorteo 396
#
# The roadmap's prompt assumed "the expected value is exactly zero". It is 6.5%, and that
# number is the whole reason this sub-PR exists before the quarantine store: an alarm on
# total rejects would fire every single Thursday and be muted within a month. The signal is
# REJECT_UNRECOGNISED, which has fired **once in 118 draws**.

#: A millar heading — `CENTENARES`, `00MIL`, `DOS MIL`, `TREINTA Y UN MIL`. Structure, not
#: data: it introduces the block of prizes that follows. 113 distinct values in the archive.
REJECT_SECTION_HEADER = "section_header"

#: A `VENDIDO POR` / `NO VENDIDO` line with no premio before it to attach to. Never observed
#: in the archive, and kept precisely because of that: it is the shape the body would take if
#: the site reordered its blocks, and a code that has never fired is how you find out.
REJECT_ORPHAN_VENDOR_LINE = "orphan_vendor_line"

#: Anything else. **This is the number worth alarming on.** One occurrence in the entire
#: archive: `00CERO` in sorteo 396, which is a typo of a section heading at the source.
REJECT_UNRECOGNISED = "unrecognised"

#: Matches a millar heading, including the archive's one typo'd `000MIL`. Deliberately
#: permissive on the leading digits: `000MIL` is structurally a heading and reading it as one
#: is more honest than reporting it as data loss. A stricter `00MIL` would make it a second
#: REJECT_UNRECOGNISED — defensible too, and the reason this choice is written down.
_SECTION_HEADER_RE = re.compile(r"^(?:CENTENARES|\d*MIL|[A-ZÁÉÍÓÚÑ ]+MIL)$")

#: Rejected lines are logged and (in PR-044.2) stored. Truncated so one malformed file
#: cannot write a megabyte of log lines, and because the leading characters are what
#: identify the shape.
REJECT_LINE_MAX = 120


def process_body(body):
    """Extract premios from the BODY section, and report what was dropped.

    Returns ``(premios_data, rejects)`` — PR-044.1 changed this from a bare list, and the
    change IS the point. Before it, unmatched lines fell into an ``else`` that logged at
    DEBUG; Glue does not run at DEBUG, so the line vanished and ``premios_count`` was
    reported with no denominator. Silent loss is the worst failure mode a pipeline has,
    because every downstream number still looks plausible.

    Each reject is ``{"line": <truncated>, "reason": <code>, "position": <1-based index>}``.
    The caller decides what to do with them; this function still skips the row either way,
    because **a rejected line must never fail the run by itself** — one odd footer line
    turning into a missed week of ingestion is a worse outcome than the line being dropped.
    """
    premios_data = []
    rejects = []
    last_premio_index = None  # Índice del último premio procesado

    logger.debug("Processing BODY section")
    lines_total = 0
    position = 0
    for position, raw_line in enumerate(body, start=1):
        line = raw_line.strip()
        if not line:
            # Blank lines are formatting, not content: they are not counted and not
            # rejected. Counting them would inflate the denominator and make the reject
            # RATE — which is what PR-044.2's alarm is built on — depend on whitespace.
            continue
        lines_total += 1

        logger.debug("Processing line", extra={"line": line})

        # Intentar coincidir con una línea de premio
        match = re.match(r"(\d+)\s+(\w+)\s+\.+\s+([\d,]+\.?\d*)", line)
        if match:
            numero_premiado, letras, monto = match.groups()
            monto = float(monto.replace(",", ""))  # Limpiar el monto
            # reintegro = int(numero_premiado[-1]) # Extract the last digit

            premios_data.append(
                {
                    "numero_premiado": numero_premiado,
                    "letras": letras,
                    "monto": monto,
                    # "reintegro": reintegro, # Add reintegro column
                    "vendido_por": None,  # Default Value to None
                    "ciudad": None,
                    "departamento": None,
                }
            )
            last_premio_index = len(premios_data) - 1  # Guarda el índice actual

        elif ("VENDIDO POR" in line or "NO VENDIDO" in line) and last_premio_index is None:
            # A vendor line with no premio to attach to. Never seen in the archive, which is
            # exactly why it has a code of its own: it is the shape the body takes if the
            # site reorders its blocks, and "never fired" is only knowable if it can fire.
            rejects.append(
                {
                    "line": line[:REJECT_LINE_MAX],
                    "reason": REJECT_ORPHAN_VENDOR_LINE,
                    "position": position,
                }
            )
            logger.info(
                "Body line rejected",
                extra={
                    "line": line[:REJECT_LINE_MAX],
                    "reason": REJECT_ORPHAN_VENDOR_LINE,
                    "position": position,
                },
            )

        elif "VENDIDO POR" in line and last_premio_index is not None:
            # Si encontramos "VENDIDO POR", asignar al último premio
            current_vendedor = line.split("VENDIDO POR", 1)[1].strip()
            premios_data[last_premio_index]["vendido_por"] = current_vendedor

        elif "NO VENDIDO" in line and last_premio_index is not None:
            # Asignar "NO VENDIDO" con valores predeterminados
            premios_data[last_premio_index]["vendido_por"] = "NO VENDIDO"
            premios_data[last_premio_index]["ciudad"] = (
                None  # Adding "None" for compatilibility with SQL
            )
            premios_data[last_premio_index]["departamento"] = None

        else:
            # PR-044.1: was `logger.debug("Ignored line", ...)`, which Glue never emitted.
            reason = (
                REJECT_SECTION_HEADER if _SECTION_HEADER_RE.match(line) else REJECT_UNRECOGNISED
            )
            rejects.append({"line": line[:REJECT_LINE_MAX], "reason": reason, "position": position})
            # INFO, not DEBUG or WARNING. DEBUG is invisible in Glue, which is how this got
            # lost in the first place; WARNING would cry wolf 9,464 times per archive on
            # lines that are ordinary structure.
            logger.info(
                "Body line rejected",
                extra={"line": line[:REJECT_LINE_MAX], "reason": reason, "position": position},
            )

    by_reason = Counter(r["reason"] for r in rejects)
    logger.info(
        "Premios processed",
        extra={
            "premios_count": len(premios_data),
            # The denominator the old log line never had.
            "lines_total": lines_total,
            "lines_parsed": lines_total - len(rejects),
            "lines_rejected": len(rejects),
            "rejected_section_header": by_reason.get(REJECT_SECTION_HEADER, 0),
            "rejected_orphan_vendor_line": by_reason.get(REJECT_ORPHAN_VENDOR_LINE, 0),
            # The one to watch. Baseline across the whole archive: 1 line in 145,680.
            "rejected_unrecognised": by_reason.get(REJECT_UNRECOGNISED, 0),
        },
    )
    return premios_data, rejects


def split_vendido_por_column(df):
    """
    Splits the 'vendido_por' column into 'vendedor', 'ciudad', and 'departamento'.
    Args:
        df (pd.DataFrame): DataFrame with 'vendido_por' column.
    Returns:
        pd.DataFrame: DataFrame with new columns and 'vendido_por' removed.
    """
    split_data = df["vendido_por"].str.split(r",", expand=True)  # separates the info by using ","
    df["vendedor"] = split_data[0].str.strip()  # Extract vendor name
    df["ciudad"] = split_data[1].str.strip() if split_data.shape[1] > 1 else None  # Extract city
    df["departamento"] = (
        split_data[2].str.strip() if split_data.shape[1] > 2 else None
    )  # Extract department
    df.drop(columns=["vendido_por"], inplace=True)  # Remove original column
    return df
