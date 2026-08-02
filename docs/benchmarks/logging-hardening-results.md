# Logging and shutdown hardening benchmark

Date: 2026-08-02

Change: suppress URL-bearing dependency INFO loggers at the executable boundary,
serialize only exception types rather than traceback paths, and treat Ctrl-C as
a normal MCP shutdown.

The complete 21-stage offline harness was captured immediately before and after
the change:

- Before SHA-256: `48f52146d288bf805408f0ff0374cd1f3083ccedb9d60ae97b4dbad3d4ed7fdc`
- After SHA-256: `c248a1fe6326869e984a0977c668d4afad90fe9ec276fec757703cc1c8ba15e4`

The only output difference was the measured Stage 10 SQLite/fusion fixture,
from 0.5947 ms to 0.6596 ms. Accuracy and reliability outputs are otherwise
byte-equivalent; the 0.0649 ms observation is noise-scale and is not a speed
claim.

Tests verify that dependency logger levels are at least `WARNING`, exception
messages and source paths are not serialized, imports still do not configure
global logging, and `KeyboardInterrupt` exits the server boundary normally.
