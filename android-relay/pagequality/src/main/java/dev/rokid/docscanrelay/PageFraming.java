package dev.rokid.docscanrelay;

import java.util.EnumSet;
import java.util.Locale;
import java.util.Set;

/**
 * Recognised-text border evidence, not physical paper or content completeness.
 *
 * <p>ponytail: text boxes cannot see unrecognised text, diagrams or a lost blank
 * margin. A separately calibrated paper/content detector is needed for admission.</p>
 * Kept free of Android/ML Kit types; JapaneseOcr feeds the boxes in.
 */
public final class PageFraming {
    /** Fraction of each dimension treated as the border band. */
    private static final double EDGE_BAND_RATIO = 0.02;

    /** Never let the band collapse on a small image. */
    private static final int MIN_EDGE_BAND_PIXELS = 6;

    public enum Verdict {
        /** No text was located, so framing cannot be judged from text at all. */
        NO_TEXT,
        /** Text reaches a border: clipping is suspected, not proved. */
        CLIPPED,
        /** Located text is inside the border; unrecognised content is unknown. */
        TEXT_BOUNDS_ONLY,
        /** Restored from an older record that predates this check. */
        UNKNOWN
    }

    public enum Side {
        LEFT("左"),
        TOP("上"),
        RIGHT("右"),
        BOTTOM("下");

        private final String label;

        Side(String label) {
            this.label = label;
        }

        String label() {
            return label;
        }
    }

    public static final PageFraming UNKNOWN =
            new PageFraming(Verdict.UNKNOWN, EnumSet.noneOf(Side.class), 0);

    private final Verdict verdict;
    private final Set<Side> clippedSides;
    private final int lineCount;

    private PageFraming(Verdict verdict, Set<Side> clippedSides, int lineCount) {
        this.verdict = verdict;
        this.clippedSides = clippedSides;
        this.lineCount = lineCount;
    }

    public static Builder builder(int imageWidth, int imageHeight) {
        return new Builder(imageWidth, imageHeight);
    }

    public Verdict verdict() {
        return verdict;
    }

    public Set<Side> clippedSides() {
        // Always an EnumSet, so copyOf is safe even when it is empty.
        return EnumSet.copyOf(clippedSides);
    }

    public int lineCount() {
        return lineCount;
    }

    /** True when the operator should be steered to a retake rather than a save. */
    public boolean isFailing() {
        return verdict == Verdict.CLIPPED;
    }

    /** One HUD-sized line, no wider than the three-line contract allows. */
    public String describe() {
        switch (verdict) {
            case TEXT_BOUNDS_ONLY:
                return "文字枠のみ・紙面未確認";
            case CLIPPED:
                return describeClippedSides() + "が切れています";
            case NO_TEXT:
                return "文字が見つからず判定不可";
            case UNKNOWN:
            default:
                return "判定情報なし";
        }
    }

    private String describeClippedSides() {
        StringBuilder sides = new StringBuilder();
        for (Side side : Side.values()) {
            if (clippedSides.contains(side)) {
                sides.append(side.label());
            }
        }
        return sides.length() == 0 ? "端" : sides.toString();
    }

    /** Compact token used by the pending-capture record. */
    public String toToken() {
        StringBuilder token = new StringBuilder(verdict.name());
        if (verdict == Verdict.CLIPPED) {
            token.append(':');
            for (Side side : Side.values()) {
                if (clippedSides.contains(side)) {
                    token.append(side.name().charAt(0));
                }
            }
        }
        return token.append('#').append(lineCount).toString();
    }

    public static PageFraming fromToken(String token) {
        if (token == null || token.isEmpty()) {
            return UNKNOWN;
        }
        int countAt = token.lastIndexOf('#');
        int lineCount = 0;
        String head = token;
        if (countAt >= 0) {
            head = token.substring(0, countAt);
            try {
                lineCount = Integer.parseInt(token.substring(countAt + 1));
            } catch (NumberFormatException ignored) {
                lineCount = 0;
            }
        }
        int sidesAt = head.indexOf(':');
        String name = sidesAt < 0 ? head : head.substring(0, sidesAt);
        Verdict verdict;
        try {
            verdict = "COMPLETE".equals(name) ? Verdict.TEXT_BOUNDS_ONLY : Verdict.valueOf(name);
        } catch (IllegalArgumentException ignored) {
            return UNKNOWN;
        }
        EnumSet<Side> sides = EnumSet.noneOf(Side.class);
        if (sidesAt >= 0) {
            String letters = head.substring(sidesAt + 1);
            for (Side side : Side.values()) {
                if (letters.indexOf(side.name().charAt(0)) >= 0) {
                    sides.add(side);
                }
            }
        }
        return new PageFraming(verdict, sides, Math.max(0, lineCount));
    }

    @Override
    public String toString() {
        return String.format(
                Locale.US, "%s lines=%d", describe(), lineCount);
    }

    public static final class Builder {
        private final int imageWidth;
        private final int imageHeight;
        private final EnumSet<Side> clippedSides = EnumSet.noneOf(Side.class);
        private int lineCount;

        private Builder(int imageWidth, int imageHeight) {
            this.imageWidth = imageWidth;
            this.imageHeight = imageHeight;
        }

        /**
         * Adds one recognised line's bounding box, in the coordinate space of
         * the upright image the recogniser was given.
         */
        public Builder addLineBounds(int left, int top, int right, int bottom) {
            if (imageWidth <= 0 || imageHeight <= 0) {
                return this;
            }
            if (right < left || bottom < top) {
                return this;
            }
            lineCount++;
            int horizontalBand = band(imageWidth);
            int verticalBand = band(imageHeight);
            if (left <= horizontalBand) {
                clippedSides.add(Side.LEFT);
            }
            if (top <= verticalBand) {
                clippedSides.add(Side.TOP);
            }
            if (right >= imageWidth - horizontalBand) {
                clippedSides.add(Side.RIGHT);
            }
            if (bottom >= imageHeight - verticalBand) {
                clippedSides.add(Side.BOTTOM);
            }
            return this;
        }

        private static int band(int dimension) {
            return Math.max(
                    MIN_EDGE_BAND_PIXELS,
                    (int) Math.round(dimension * EDGE_BAND_RATIO));
        }

        public PageFraming build() {
            if (imageWidth <= 0 || imageHeight <= 0) {
                return UNKNOWN;
            }
            if (lineCount == 0) {
                return new PageFraming(
                        Verdict.NO_TEXT, EnumSet.noneOf(Side.class), 0);
            }
            if (!clippedSides.isEmpty()) {
                return new PageFraming(
                        Verdict.CLIPPED, EnumSet.copyOf(clippedSides), lineCount);
            }
            return new PageFraming(
                    Verdict.TEXT_BOUNDS_ONLY, EnumSet.noneOf(Side.class), lineCount);
        }
    }
}
