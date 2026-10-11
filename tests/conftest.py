"""Test against real Home Assistant entities, flows and script services."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield
