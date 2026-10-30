"""Enable the actual integration in Home Assistant framework tests."""

import pytest


@pytest.fixture(autouse=True)
def local_http_contract_sockets(request):
    """Only the loopback HTTP contract tests require real sockets."""
    if request.module.__name__.endswith("test_client"):
        request.getfixturevalue("socket_enabled")


@pytest.fixture(autouse=True)
def enable_tivimuse(enable_custom_integrations):
    yield
