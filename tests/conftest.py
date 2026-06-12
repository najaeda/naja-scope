# SPDX-License-Identifier: Apache-2.0
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
UART_SV = os.path.join(FIXTURES, "uart.sv")


@pytest.fixture(scope="session")
def uart_session():
    """One loaded uart design for the whole test session (the universe is
    process-global; reloading per test would be slow and pointless)."""
    from naja_scope.session import SESSION

    SESSION.reset()
    SESSION.load_systemverilog([UART_SV])
    yield SESSION
