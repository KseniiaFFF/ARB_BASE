import logging


def setup_logging():
    logging.basicConfig(
        filename="log_ARBITRATION_bot.txt",
        level=logging.INFO,
        encoding="utf-8",
        format=(
            "%(asctime)s - "
            "%(name)s - "
            "%(levelname)s - "
            "%(message)s"
        )
    )