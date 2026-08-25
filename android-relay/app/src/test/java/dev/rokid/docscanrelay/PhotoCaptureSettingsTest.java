package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.List;
import org.junit.Test;

public class PhotoCaptureSettingsTest {
    @Test
    public void defaultsToTheClientLValuesThatStayWithinTheBinderCallbackLimit() {
        PhotoCaptureSettings defaults = PhotoCaptureSettings.DEFAULT;

        assertEquals(1920, defaults.width);
        assertEquals(1080, defaults.height);
        assertEquals(80, defaults.quality);
    }

    @Test
    public void describesItselfInTakePhotoArgumentOrder() {
        assertEquals("1920x1080 q80", PhotoCaptureSettings.DEFAULT.describe());
    }

    @Test
    public void parsesOperatorEnteredSweepValues() {
        PhotoCaptureSettings parsed = PhotoCaptureSettings.parse("4032", "3024", "50");

        assertEquals(4032, parsed.width);
        assertEquals(3024, parsed.height);
        assertEquals(50, parsed.quality);
    }

    @Test
    public void parseTrimsSurroundingWhitespace() {
        PhotoCaptureSettings parsed = PhotoCaptureSettings.parse(" 2560 ", " 1920 ", " 60 ");

        assertEquals("2560x1920 q60", parsed.describe());
    }

    @Test
    public void rejectsNonNumericInput() {
        assertThrows(
                IllegalArgumentException.class,
                () -> PhotoCaptureSettings.parse("1920", "ten-eighty", "80"));
    }

    @Test
    public void rejectsNonPositiveDimensions() {
        assertThrows(
                IllegalArgumentException.class,
                () -> PhotoCaptureSettings.parse("0", "1080", "80"));
        assertThrows(
                IllegalArgumentException.class,
                () -> PhotoCaptureSettings.parse("1920", "-1", "80"));
    }

    @Test
    public void rejectsDimensionsBeyondTheGlassesSensor() {
        assertThrows(
                IllegalArgumentException.class,
                () -> PhotoCaptureSettings.parse("8000", "6000", "80"));
    }

    @Test
    public void rejectsQualityOutsideTheJpegRange() {
        assertThrows(
                IllegalArgumentException.class,
                () -> PhotoCaptureSettings.parse("1920", "1080", "0"));
        assertThrows(
                IllegalArgumentException.class,
                () -> PhotoCaptureSettings.parse("1920", "1080", "101"));
    }

    @Test
    public void rejectionMessageNamesTheOffendingField() {
        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> PhotoCaptureSettings.parse("1920", "1080", "101"));

        assertTrue(error.getMessage().contains("品質"));
    }

    @Test
    public void sweepPresetsStartAtTheKnownGoodBaseline() {
        List<PhotoCaptureSettings> presets = PhotoCaptureSettings.SWEEP_PRESETS;

        assertEquals(PhotoCaptureSettings.DEFAULT.describe(), presets.get(0).describe());
    }

    @Test
    public void sweepPresetsPutTheDecisiveTwelveMegapixelProbeSecond() {
        // 4032x3024 at q50 is small enough that a failure cannot be blamed on
        // the Binder payload budget, which is what makes it the discriminator.
        assertEquals("4032x3024 q50", PhotoCaptureSettings.SWEEP_PRESETS.get(1).describe());
    }

    @Test
    public void sweepPresetsAreDistinct() {
        List<PhotoCaptureSettings> presets = PhotoCaptureSettings.SWEEP_PRESETS;

        for (int i = 0; i < presets.size(); i++) {
            for (int j = i + 1; j < presets.size(); j++) {
                assertNotEquals(presets.get(i).describe(), presets.get(j).describe());
            }
        }
    }

    @Test
    public void restoresPersistedValues() {
        PhotoCaptureSettings restored =
                PhotoCaptureSettings.ofOrDefault(3264, 2448, 60);

        assertEquals("3264x2448 q60", restored.describe());
    }

    @Test
    public void restoringInvalidPersistedValuesFallsBackToTheDefault() {
        PhotoCaptureSettings restored = PhotoCaptureSettings.ofOrDefault(0, 0, 999);

        assertEquals(PhotoCaptureSettings.DEFAULT.describe(), restored.describe());
    }

    @Test
    public void steppingTheSweepMovesToTheNextProbeInOrder() {
        PhotoCaptureSettings next = PhotoCaptureSettings.nextPreset(PhotoCaptureSettings.DEFAULT);

        assertEquals(PhotoCaptureSettings.SWEEP_PRESETS.get(1).describe(), next.describe());
    }

    @Test
    public void steppingPastTheLastProbeReturnsToTheBaseline() {
        List<PhotoCaptureSettings> presets = PhotoCaptureSettings.SWEEP_PRESETS;

        PhotoCaptureSettings next = PhotoCaptureSettings.nextPreset(presets.get(presets.size() - 1));

        assertEquals(PhotoCaptureSettings.DEFAULT.describe(), next.describe());
    }

    @Test
    public void steppingFromAHandEnteredValueRestartsTheSweepAtTheBaseline() {
        // The operator can type anything; the sweep still has to be resumable.
        PhotoCaptureSettings custom = PhotoCaptureSettings.parse("1600", "1200", "77");

        assertEquals(
                PhotoCaptureSettings.DEFAULT.describe(),
                PhotoCaptureSettings.nextPreset(custom).describe());
    }
}
