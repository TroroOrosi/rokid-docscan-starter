package dev.rokid.docscanrelay;

/**
 * Selects replaceable page indexes after a zero-problem finalize.
 *
 * <p>The document is already finalized at that point, so only existing indexes
 * may be uploaded. Short presses walk those indexes from the first page while
 * a double short press can revisit the preceding retry target.</p>
 */
final class RetryCursor {
    private int pageIndex = -1;
    private int pageLimit;

    void begin(int existingPageCount) {
        pageLimit = Math.max(0, existingPageCount);
        pageIndex = pageLimit > 0 ? 0 : -1;
    }

    void clear() {
        pageIndex = -1;
        pageLimit = 0;
    }

    boolean isActive() {
        return pageIndex >= 0 && pageIndex < pageLimit;
    }

    int nextOr(int nextPageIndex) {
        return isActive() ? pageIndex : nextPageIndex;
    }

    int previousOr(int nextPageIndex) {
        if (isActive()) {
            return pageIndex > 0 ? pageIndex - 1 : -1;
        }
        return nextPageIndex > 0 ? nextPageIndex - 1 : -1;
    }

    void onUploaded(int uploadedPageIndex) {
        if (!isActive() || uploadedPageIndex != pageIndex) {
            return;
        }
        pageIndex++;
        if (pageIndex >= pageLimit) {
            clear();
        }
    }
}
