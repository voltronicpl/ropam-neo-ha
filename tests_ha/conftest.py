"""Testy integracji w środowisku Home Assistant."""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def no_frontend(hass):
    """Frontend/http nie są dostępne w testach - oznaczamy je jako załadowane."""
    for comp in ("frontend", "http", "websocket_api"):
        hass.config.components.add(comp)
    yield
