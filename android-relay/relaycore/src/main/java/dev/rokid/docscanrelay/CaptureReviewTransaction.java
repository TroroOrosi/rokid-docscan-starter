package dev.rokid.docscanrelay;

import java.io.IOException;

/**
 * Commits a pending review photo to durable storage before making it visible
 * in memory. A failed replacement therefore leaves the previous review photo
 * authoritative in both places.
 */
final class CaptureReviewTransaction {
    interface Saver {
        void save(CaptureReviewStore.Pending pending) throws IOException;
    }

    private CaptureReviewTransaction() {
    }

    static CaptureReviewStore.Pending replace(
            CaptureReviewStore store,
            CaptureReviewStore.Pending candidate,
            Saver saver
    ) throws IOException {
        saver.save(candidate);
        return store.stage(candidate);
    }
}
