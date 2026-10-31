// AGENT_APPROVED=1: authorized Android comparison tests; device dispatch zero.
package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;

import java.nio.ByteBuffer;
import org.junit.Test;

/** Proposal geometry only: none of these observations certifies a complete paper page. */
public class PaperGeometryTest {
    @Test public void paddedPixelStridesAndBufferPositionKeepTheSameNonDestructiveCandidate() {
        byte[] bytes = new byte[7 + 48 * 137];
        java.util.Arrays.fill(bytes, (byte) 4);
        for (int y = 0; y < 48; y++) for (int x = 0; x < 64; x++) {
            bytes[7 + y * 137 + x * 2] = (byte)(x >= 16 && x < 48 && y >= 12 && y < 36 ? 220 : 20);
        }
        byte[] before = bytes.clone();
        ByteBuffer plane = ByteBuffer.wrap(bytes); plane.position(7);
        PaperGeometry.Box candidate = PaperGeometry.candidate(plane, 64, 48, 137, 2);
        assertNotNull(candidate);
        // Existing PaperCrop keeps two grid cells horizontally and one vertically as margin.
        assertArrayEquals(new int[]{14, 11, 50, 37}, candidate.edges()); // AGENT_APPROVED=1
        assertArrayEquals(before, bytes); assertEquals(7, plane.position());
    }

    @Test public void rotationAndSensorLetterboxUseTheWholeOriginalCoordinateSystem() {
        PaperGeometry.Box box = new PaperGeometry.Box(16, 12, 48, 36, 64, 48);
        assertArrayEquals(new int[]{12, 16, 36, 48}, box.rotate(90).edges());
        assertArrayEquals(new int[]{16, 12, 48, 36}, box.rotate(180).edges());
        assertArrayEquals(new int[]{12, 16, 36, 48}, box.rotate(270).edges());
        // Independent 16:9 example: 4000x3000 crops 375px from each vertical edge.
        assertArrayEquals(new int[]{1000, 937, 3000, 2063}, box.sensorRegion(0, 0, 4000, 3000, 16, 9));
    }

    @Test public void uncertaintyAndSeparateScenesNeverReuseThePreviousPaperCandidate() {
        PaperGeometry.Tracker tracker = new PaperGeometry.Tracker();
        PaperGeometry.Box a = new PaperGeometry.Box(8, 8, 56, 40, 64, 48);
        assertNull(tracker.observe(a, 1)); assertSame(a, tracker.observe(a, 1));
        assertNull(tracker.observe(null, 1));
        assertNull(tracker.observe(a, 2)); assertSame(a, tracker.observe(a, 2));
        assertNull(tracker.observe(a, 3)); assertSame(a, tracker.observe(a, 3));
        assertNull(tracker.observe(a, 1)); // stale scene cannot resurrect the earlier A.
    }

    @Test public void lowContrastClippedEdgesAndShortPlanesRemainUnknownWithoutDiscardingPixels() {
        byte[] page = new byte[64 * 48]; java.util.Arrays.fill(page, (byte)200); // AGENT_APPROVED=1
        assertNull(PaperGeometry.candidate(ByteBuffer.wrap(page), 64, 48, 64, 1));
        java.util.Arrays.fill(page, (byte)20);
        for (int y = 12; y < 36; y++) java.util.Arrays.fill(page, y * 64, y * 64 + 32, (byte)220);
        byte[] original = page.clone();
        assertNull("a bright object touching an edge is not a complete-page observation",
                PaperGeometry.candidate(ByteBuffer.wrap(page), 64, 48, 64, 1));
        assertNull(PaperGeometry.candidate(ByteBuffer.wrap(page, 0, page.length - 1), 64, 48, 64, 1));
        assertArrayEquals(original, page);
    }
}
