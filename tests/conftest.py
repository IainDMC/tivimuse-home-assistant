"""Enable the actual integration in Home Assistant framework tests."""

import pytest


@pytest.fixture(autouse=True)
def enable_tivimuse(enable_custom_integrations):
    yield
