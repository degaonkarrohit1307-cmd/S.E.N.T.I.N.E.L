"""WeatherPlugin -- demo entry point proving v0.3.4 dynamic import."""
from __future__ import annotations

import logging

logger = logging.getLogger("sentinel.plugins.weather")


class WeatherPlugin:
    def on_load(self) -> None:
        logger.info("weather plugin loaded")

    def on_initialize(self) -> None:
        logger.info("weather plugin initialized")

    def on_start(self) -> None:
        logger.info("weather plugin started")

    def on_stop(self) -> None:
        logger.info("weather plugin stopped")

    def on_unload(self) -> None:
        logger.info("weather plugin unloaded")
