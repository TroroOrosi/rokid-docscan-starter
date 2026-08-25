package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class OcrQualityTest {
    @Test
    public void aCaptureThatRecognisedNothingReportsZeroRatherThanFailing() {
        OcrQuality quality = OcrQuality.builder().build();

        assertEquals(0, quality.characterCount());
        assertEquals("0文字 確信度不明", quality.describe());
    }

    @Test
    public void countsRecognisedCharactersIgnoringLayoutWhitespace() {
        OcrQuality quality = OcrQuality.builder()
                .addSymbol("二", 0.9f)
                .addSymbol("次", 0.9f)
                .addSymbol(" ", 0.9f)
                .addSymbol("\n", 0.9f)
                .addSymbol("式", 0.9f)
                .build();

        assertEquals(3, quality.characterCount());
    }

    @Test
    public void meanConfidenceAveragesOverRecognisedSymbols() {
        OcrQuality quality = OcrQuality.builder()
                .addSymbol("A", 0.6f)
                .addSymbol("B", 0.8f)
                .build();

        assertEquals(0.7f, quality.meanConfidence(), 0.0001f);
        assertEquals("2文字 確信度0.70", quality.describe());
    }

    @Test
    public void symbolsWithoutConfidenceStillCountAsRecognisedCharacters() {
        // The unbundled recogniser omits confidence; the character count is
        // still the signal that tells the operator the page was readable.
        OcrQuality quality = OcrQuality.builder()
                .addSymbol("A", null)
                .addSymbol("B", null)
                .build();

        assertEquals(2, quality.characterCount());
        assertEquals("2文字 確信度不明", quality.describe());
    }

    @Test
    public void meanConfidenceUsesOnlyTheSymbolsThatReportedIt() {
        OcrQuality quality = OcrQuality.builder()
                .addSymbol("A", 0.4f)
                .addSymbol("B", null)
                .addSymbol("C", 0.6f)
                .build();

        assertEquals(0.5f, quality.meanConfidence(), 0.0001f);
        assertEquals("3文字 確信度0.50", quality.describe());
    }

    @Test
    public void confidenceBelowTheThresholdMarksTheCaptureAsUnreliable() {
        OcrQuality unreliable = OcrQuality.builder().addSymbol("A", 0.49f).build();
        OcrQuality reliable = OcrQuality.builder().addSymbol("A", 0.5f).build();

        assertTrue(unreliable.isLowConfidence());
        assertFalse(reliable.isLowConfidence());
    }

    @Test
    public void aCaptureWithoutConfidenceDataIsNotAccusedOfBeingUnreliable() {
        OcrQuality quality = OcrQuality.builder().addSymbol("A", null).build();

        assertFalse(quality.isLowConfidence());
    }

    @Test
    public void multiCharacterSymbolsContributeEveryCharacter() {
        OcrQuality quality = OcrQuality.builder().addSymbol("12", 0.9f).build();

        assertEquals(2, quality.characterCount());
    }
}
