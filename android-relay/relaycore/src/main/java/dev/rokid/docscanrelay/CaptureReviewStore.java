package dev.rokid.docscanrelay;

/**
 * Holds an unregistered photo while the user checks framing and focus.
 *
 * <p>The original JPEG remains authoritative for upload. The phone preview
 * may decode a smaller bitmap, but it must never replace these bytes.</p>
 */
final class CaptureReviewStore {
    static final class Confirmation {
        private final Pending pending;

        private Confirmation(Pending pending) {
            this.pending = pending;
        }

        Pending pending() {
            return pending;
        }
    }

    static final class Pending {
        final int pageIndex;
        final byte[] jpeg;
        final String ocrText;
        final int rotationDegrees;
        final String ocrFailure;
        final PageFraming framing;
        final long capturedAtMillis;

        Pending(
                int pageIndex,
                byte[] jpeg,
                String ocrText,
                int rotationDegrees,
                String ocrFailure
        ) {
            this(pageIndex, jpeg, ocrText, rotationDegrees, ocrFailure, null);
        }

        Pending(
                int pageIndex,
                byte[] jpeg,
                String ocrText,
                int rotationDegrees,
                String ocrFailure,
                PageFraming framing
        ) {
            this(pageIndex, jpeg, ocrText, rotationDegrees, ocrFailure, framing, 0);
        }

        Pending(int pageIndex, byte[] jpeg, String ocrText, int rotationDegrees,
                String ocrFailure, PageFraming framing, long capturedAtMillis) {
            this.pageIndex = pageIndex;
            this.jpeg = jpeg;
            this.ocrText = ocrText == null ? "" : ocrText;
            this.rotationDegrees = rotationDegrees;
            this.ocrFailure = ocrFailure == null ? "" : ocrFailure;
            this.framing = framing == null ? PageFraming.UNKNOWN : framing;
            this.capturedAtMillis = capturedAtMillis;
        }

        int ocrCharacters() {
            return ocrText.length();
        }

        boolean hasOcrFailure() {
            return !ocrFailure.isEmpty();
        }

        /** True when the framing check says the page ran outside the frame. */
        boolean isFramingFailing() {
            return framing.isFailing();
        }
    }

    private Pending pending;

    synchronized Pending stage(
            int pageIndex,
            byte[] jpeg,
            String ocrText,
            int rotationDegrees,
            String ocrFailure
    ) {
        return stage(new Pending(
                pageIndex,
                jpeg,
                ocrText,
                rotationDegrees,
                ocrFailure));
    }

    synchronized Pending stage(Pending candidate) {
        if (candidate == null) {
            throw new IllegalArgumentException("pending capture is required");
        }
        pending = candidate;
        return pending;
    }

    synchronized Pending peek() {
        return pending;
    }

    synchronized boolean hasPending() {
        return pending != null;
    }

    synchronized Confirmation confirm() {
        return pending == null ? null : new Confirmation(pending);
    }

    synchronized boolean clear(Confirmation confirmation) {
        return confirmation != null && clear(confirmation.pending);
    }

    synchronized boolean clear(Pending expected) {
        if (pending != expected) {
            return false;
        }
        pending = null;
        return true;
    }

    synchronized void clear() {
        pending = null;
    }
}
