"""Bundle captured page images into one PDF.

Two callers want the same thing for different reasons: the ChatGPT web solver
can send a 大問 as a single document instead of one upload per page, and the
phone path needs one file the operator can attach by hand. Attaching a dozen
photos on a phone is the part of the manual route that does not survive a real
session; one file does.

The pages are converted to RGB because a PNG with an alpha channel cannot be
written to PDF, and the server stores normalized PNGs.
"""

from __future__ import annotations

import io


def images_to_pdf(images: list[bytes]) -> bytes:
    """Return one PDF holding ``images`` in the order given.

    Raises ValueError on an empty list rather than writing an empty PDF: an
    empty attachment reads as "the figures were sent" and they were not.
    """
    from PIL import Image  # noqa: PLC0415 - keeps PIL off the import path of callers

    if not images:
        raise ValueError("no page images to bundle")
    frames = [Image.open(io.BytesIO(data)).convert("RGB") for data in images]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="PDF", save_all=True, append_images=frames[1:])
    return buffer.getvalue()
