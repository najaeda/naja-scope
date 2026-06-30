# SPDX-License-Identifier: Apache-2.0
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
UART_SV = os.path.join(FIXTURES, "uart.sv")


@pytest.fixture
def uart_session():
    """A freshly loaded uart design for each test that needs it.

    The naja universe is process-global and other test modules load different
    designs (gate netlists, intent fixtures) into it, so a cached session-scoped
    fixture would hand later tests whatever design ran last — order- and
    platform-dependent breakage. Reloading the ~110-line uart is ~0.02s, so we
    just (re)load it per test and stay isolated."""
    from naja_scope.session import SESSION

    SESSION.reset()
    SESSION.load_systemverilog([UART_SV])
    yield SESSION
