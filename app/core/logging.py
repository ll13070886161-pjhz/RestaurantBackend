import logging


def setup_logging(log_level: str) -> None:
    level = getattr(logging, (log_level or "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
