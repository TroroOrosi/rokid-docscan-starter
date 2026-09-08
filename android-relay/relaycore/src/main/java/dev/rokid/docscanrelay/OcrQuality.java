package dev.rokid.docscanrelay;

import java.util.Locale;

/**
 * How much text the on-phone recogniser actually resolved, and how sure it was.
 *
 * <p>A capture that returns text is not the same as a capture that returns
 * usable text. The glasses use a 109-degree lens, so a page photographed from a
 * natural reading distance can land below the per-character pixel size ML Kit
 * needs, and the recogniser then answers with a short string of confidently
 * wrong characters. Character count alone cannot tell those apart, so the mean
 * symbol confidence is aggregated alongside it and shown to the operator.</p>
 *
 * <p>Aggregation is kept free of ML Kit types so the arithmetic is testable
 * without a device or a recogniser stub; {@link JapaneseOcr} walks the result
 * tree and feeds symbols in.</p>
 */
public final class OcrQuality {
    /** Below this, the text is more likely to be misread than merely imperfect. */
    public static final float LOW_CONFIDENCE_THRESHOLD = 0.5f;

    private final int characterCount;
    private final int confidenceSamples;
    private final float meanConfidence;

    private OcrQuality(int characterCount, int confidenceSamples, float meanConfidence) {
        this.characterCount = characterCount;
        this.confidenceSamples = confidenceSamples;
        this.meanConfidence = meanConfidence;
    }

    public static Builder builder() {
        return new Builder();
    }

    public int characterCount() {
        return characterCount;
    }

    /** Mean over the symbols that reported a confidence, or zero if none did. */
    public float meanConfidence() {
        return meanConfidence;
    }

    public boolean hasConfidence() {
        return confidenceSamples > 0;
    }

    public boolean isLowConfidence() {
        return hasConfidence() && meanConfidence < LOW_CONFIDENCE_THRESHOLD;
    }

    public String describe() {
        String confidence = hasConfidence()
                ? String.format(Locale.US, "%.2f", meanConfidence)
                : "不明";
        return characterCount + "文字 確信度" + confidence;
    }

    public static final class Builder {
        private int characterCount;
        private int confidenceSamples;
        private double confidenceTotal;

        public Builder addSymbol(String text, Float confidence) {
            if (text != null) {
                for (int i = 0; i < text.length(); i++) {
                    if (!Character.isWhitespace(text.charAt(i))) {
                        characterCount++;
                    }
                }
            }
            if (confidence != null) {
                confidenceSamples++;
                confidenceTotal += confidence;
            }
            return this;
        }

        public OcrQuality build() {
            float mean = confidenceSamples == 0
                    ? 0f
                    : (float) (confidenceTotal / confidenceSamples);
            return new OcrQuality(characterCount, confidenceSamples, mean);
        }
    }
}
