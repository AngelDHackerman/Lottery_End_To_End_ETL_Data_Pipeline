import os

from loteria.common.logging_setup import configure_logging
from loteria.extractor.scraping import extract_lottery_data


def lambda_handler(event, context):
    event = event or {}

    # The Step Function passes CORRELATION_ID (= its execution name) in the invoke
    # payload. Promote it to the environment BEFORE configure_logging() so every log line
    # in this invocation shares the same correlation id as the Glue job in the same run.
    if event.get("CORRELATION_ID"):
        os.environ["CORRELATION_ID"] = event["CORRELATION_ID"]

    logger = configure_logging("extractor")

    lottery_number = event.get("lottery_number")  # None -> scrape último
    logger.info("Extractor invoked", extra={"lottery_number": lottery_number})

    result_path = extract_lottery_data(lottery_number)

    logger.info("Extractor finished", extra={"file": result_path})
    return {"status": "ok", "file": result_path}
