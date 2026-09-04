package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.List;

import org.junit.Test;

/**
 * The HUD is three lines of green on black. The server reports
 * {@code hud.max_lines = 3}, and the display measured 480x640 at 240dpi, so a
 * fourth line is not a cosmetic problem: it is off the glass.
 */
public final class HudLinesTest {

    @Test
    public void neverRendersMoreThanThreeLines() {
        for (ScanSession.State state : ScanSession.State.values()) {
            List<String> lines = HudLines.render(state, 7, 5, "a very long error message indeed");

            assertTrue(state + " produced " + lines.size() + " lines",
                    lines.size() <= HudLines.MAX_LINES);
        }
    }

    @Test
    public void tellsTheOperatorToOpenADocumentBeforeAnythingElse() {
        List<String> lines = HudLines.render(ScanSession.State.NO_DOCUMENT, 0, 0, "");

        assertEquals("TAP TO START", lines.get(0));
    }

    @Test
    public void showsThePageAboutToBePhotographedNotTheZeroBasedIndex() {
        List<String> lines = HudLines.render(ScanSession.State.READY, 0, 0, "");

        assertTrue("operators count from 1: " + lines, lines.contains("PAGE 1"));
    }

    @Test
    public void countsTheNextPageAfterAnAcknowledgement() {
        List<String> lines = HudLines.render(ScanSession.State.ACKED, 3, 0, "");

        assertTrue(lines.toString(), lines.contains("PAGE 4"));
    }

    @Test
    public void reportsTheBufferedPageCountWhenUploadsAreWaiting() {
        List<String> lines = HudLines.render(ScanSession.State.READY, 2, 4, "");

        assertTrue("offline pages must be visible: " + lines,
                lines.stream().anyMatch(line -> line.contains("4 WAITING")));
    }

    @Test
    public void hidesTheBufferLineWhenNothingIsWaiting() {
        List<String> lines = HudLines.render(ScanSession.State.READY, 2, 0, "");

        assertTrue(lines.toString(),
                lines.stream().noneMatch(line -> line.contains("WAITING")));
    }

    @Test
    public void truncatesALongErrorRatherThanPushingItOffTheGlass() {
        String long_error = "java.net.ConnectException: failed to connect to /192.168.0.32";

        List<String> lines = HudLines.render(ScanSession.State.FAILED, 1, 0, long_error);

        for (String line : lines) {
            assertTrue("'" + line + "' is " + line.length() + " chars",
                    line.length() <= HudLines.MAX_CHARS);
        }
        assertTrue(lines.toString(),
                lines.stream().anyMatch(line -> line.startsWith("FAILED")));
    }

    @Test
    public void neverRendersANullOrBlankLine() {
        for (ScanSession.State state : ScanSession.State.values()) {
            for (String line : HudLines.render(state, 1, 1, null)) {
                assertTrue(state + " rendered a blank line", !line.trim().isEmpty());
            }
        }
    }

    @Test
    public void namesTheStageWhileAPageIsInFlight() {
        assertTrue(HudLines.render(ScanSession.State.CAPTURING, 1, 0, "")
                .stream().anyMatch(line -> line.contains("CAPTURING")));
        assertTrue(HudLines.render(ScanSession.State.RECOGNIZING, 1, 0, "")
                .stream().anyMatch(line -> line.contains("READING")));
        assertTrue(HudLines.render(ScanSession.State.UPLOADING, 1, 0, "")
                .stream().anyMatch(line -> line.contains("SENDING")));
    }
}
