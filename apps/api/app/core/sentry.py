"""Optional Sentry integration for error tracking.

Enable by setting SENTRY_DSN environment variable.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_sentry() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured."""
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
            traces_sample_rate=float(
                os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")
            ),
            environment=os.environ.get("ENVIRONMENT", "development"),
            release=os.environ.get("IMAGE_TAG", "dev"),
            send_default_pii=False,
        )
        logger.info("Sentry error tracking enabled")
    except ImportError:
        logger.info("sentry-sdk not installed, error tracking disabled")
