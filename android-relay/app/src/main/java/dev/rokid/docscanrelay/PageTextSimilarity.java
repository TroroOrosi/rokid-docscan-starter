package dev.rokid.docscanrelay;

import java.util.HashSet;
import java.util.Set;

/**
 * Decides whether a freshly read page is the one already registered.
 *
 * <p>The automatic cycle registers a page and then starts the next burst on a
 * timer, so it will happily photograph the same sheet again if the operator
 * has not turned it yet. Comparing what was read is the only signal available:
 * the relay has no page detector and the glasses report nothing about the
 * scene.</p>
 *
 * <p>Character trigrams are used rather than whole-string equality because two
 * shots of one page never OCR identically — a few glyphs differ every time.
 * Japanese has no word boundaries to tokenise on, so trigrams over the
 * whitespace-stripped text are the cheap equivalent.</p>
 *
 * <p>ponytail: this compares text, not the sheet. Two genuinely different
 * pages that share most of their text — a form and its duplicate, a page of
 * repeated drill lines — read as the same page and the second is skipped. If
 * that shows up on real material, the fix is a page counter the operator can
 * bump, not a cleverer string metric.</p>
 */
public final class PageTextSimilarity {
    /**
     * Two shots of one page overlap far above this; consecutive pages of real
     * material sit well below it. Chosen to fail toward "different page",
     * because skipping a page the operator did turn is worse than registering
     * a near-duplicate they can delete.
     */
    public static final double SAME_PAGE_THRESHOLD = 0.8;

    /** Below this many trigrams there is not enough text to judge. */
    private static final int MIN_TRIGRAMS = 8;

    private PageTextSimilarity() {
    }

    /** Jaccard overlap of character trigrams, 0 when either side is too short. */
    public static double similarity(String left, String right) {
        Set<String> a = trigrams(left);
        Set<String> b = trigrams(right);
        if (a.size() < MIN_TRIGRAMS || b.size() < MIN_TRIGRAMS) {
            return 0;
        }
        int intersection = 0;
        for (String trigram : a) {
            if (b.contains(trigram)) {
                intersection++;
            }
        }
        int union = a.size() + b.size() - intersection;
        return union == 0 ? 0 : (double) intersection / union;
    }

    /**
     * Whether the new text is the page already registered.
     *
     * <p>Returns false when either side is too short to judge, so a page that
     * OCRs poorly is registered rather than silently dropped.</p>
     */
    public static boolean isSamePage(String registered, String candidate) {
        return similarity(registered, candidate) >= SAME_PAGE_THRESHOLD;
    }

    private static Set<String> trigrams(String text) {
        Set<String> trigrams = new HashSet<>();
        if (text == null) {
            return trigrams;
        }
        StringBuilder compact = new StringBuilder(text.length());
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (!Character.isWhitespace(c)) {
                compact.append(c);
            }
        }
        for (int i = 0; i + 3 <= compact.length(); i++) {
            trigrams.add(compact.substring(i, i + 3));
        }
        return trigrams;
    }
}
