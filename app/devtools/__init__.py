"""Developer-only diagnostic utilities (NOT part of the runtime server).

Nothing in this package is imported by the FastAPI app or the doc-scan / exam
flows. These modules are deliberate, hand-run developer tools for a device the
developer owns and controls.

IMPORTANT — privacy LED stance: the server contract advertises the camera
privacy LED as `always_on / tamper:forbidden` (see app/glasses_view.py
CAPTURE_CONTRACT) and the running service has no capability to change it. The
LED helper here is an *out-of-band* developer/diagnostic tool only. It defaults
to a dry run, never executes on import, and refuses to touch the LED unless the
operator passes explicit apply + force flags. It does not alter the server
contract and must never be wired into capture or doc-scan code paths.
"""
