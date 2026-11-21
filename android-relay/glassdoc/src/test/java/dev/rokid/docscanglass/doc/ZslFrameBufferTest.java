package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.TotalCaptureResult;
import android.media.DocScanTestImage;
import android.media.Image;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeMap;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.ShadowCaptureResult;
import org.robolectric.shadows.ShadowTotalCaptureResult;
import org.robolectric.util.ReflectionHelpers;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class ZslFrameBufferTest {
    private DocScanTestImage image(long timestamp, List<String> events) {
        DocScanTestImage image = new DocScanTestImage(events);
        image.timestamp = timestamp;
        return image;
    }
    private TotalCaptureResult result(long timestamp) {
        TotalCaptureResult result = ShadowTotalCaptureResult.newTotalCaptureResult();
        ((ShadowCaptureResult) Shadow.extract(result)).set(CaptureResult.SENSOR_TIMESTAMP, timestamp);
        return result;
    }
    @Test public void pairsInEitherOrderAndKeepsTheActualSourceResultAndImage() {
        ZslFrameBuffer ring = new ZslFrameBuffer();
        var a = image(100, new ArrayList<>()); var b = image(200, new ArrayList<>());
        var ar = result(100); var br = result(200);
        ring.image(a); assertNull(ring.latest(1, 300, r -> true));
        ring.result(ar); assertSame(ar, ring.latest(1, 300, r -> true).result);
        ring.result(br); ring.image(b);
        var selected = ring.latest(101, 300, r -> true);
        assertSame(b, selected.image); assertSame(br, selected.result);
        assertSame(selected, ring.take(selected));
        assertSame(a, ring.latest(1, 300, r -> true).image);
        assertNull("old scene and current quiet interval are both lower bounds", ring.latest(201, 300, r -> true));
        assertNull(ring.latest(1, 300, r -> false));
        b.close(); ring.close();
    }
    @Test public void boundedOrdinaryEvictionClosesOnlyEvictedImagesAndSelectedOwnerIsSeparate() {
        ZslFrameBuffer ring = new ZslFrameBuffer();
        List<String> old = new ArrayList<>(), selectedEvents = new ArrayList<>();
        var selectedImage = image(1, selectedEvents); ring.image(selectedImage); ring.result(result(1));
        var selected = ring.take(ring.latest(1, 10, r -> true));
        ring.image(image(2, old)); ring.result(result(2));
        for (long t = 3; t <= 5; t++) { ring.image(image(t, new ArrayList<>())); ring.result(result(t)); }
        assertEquals(List.of("image.close"), old);
        assertEquals(3, ring.size()); assertTrue(selectedEvents.isEmpty());
        ring.close(); assertEquals(0, ring.size()); assertTrue(selectedEvents.isEmpty());
        selected.image.close(); assertEquals(List.of("image.close"), selectedEvents);
    }
    @Test public void aNativeCloseFailureStillAttemptsEveryRemainingOwnerAndClearsTheRing() {
        ZslFrameBuffer ring = new ZslFrameBuffer(); List<String> remaining = new ArrayList<>();
        ring.image(image(1, new ArrayList<String>() {
            @Override public boolean add(String event) { throw new OutOfMemoryError("synthetic native close"); }
        }));
        ring.image(image(2, remaining));
        assertThrows(OutOfMemoryError.class, ring::close);
        assertEquals(List.of("image.close"), remaining); assertEquals(0, ring.size());
    }
    @Test public void timestampFailureClosesTheNewImageWithoutClosingExistingOwnersTwice() {
        ZslFrameBuffer ring = new ZslFrameBuffer();
        List<String> previous = new ArrayList<>(), acquired = new ArrayList<>();
        ring.image(image(1, previous));
        var failing = image(2, acquired); failing.timestampMemoryFailure = true;
        assertThrows(OutOfMemoryError.class, () -> ring.image(failing));
        assertEquals(List.of("image.close"), acquired); assertTrue(previous.isEmpty());
        ring.close(); ring.close();
        assertEquals(List.of("image.close"), acquired); assertEquals(List.of("image.close"), previous);
    }
    @Test public void allocationFailureBeforeInsertionClosesTheNewImageAndPreservesExistingOwners() {
        ZslFrameBuffer ring = new ZslFrameBuffer();
        List<String> previous = new ArrayList<>(), acquired = new ArrayList<>();
        TreeMap<Long, Image> failing = new TreeMap<>() {
            @Override public Image put(Long timestamp, Image image) {
                if (timestamp == 2) throw new OutOfMemoryError("synthetic ring allocation");
                return super.put(timestamp, image);
            }
        };
        ReflectionHelpers.setField(ring, "images", failing);
        ring.image(image(1, previous));
        assertThrows(OutOfMemoryError.class, () -> ring.image(image(2, acquired)));
        assertEquals(List.of("image.close"), acquired); assertTrue(previous.isEmpty());
        ring.close(); ring.close();
        assertEquals(List.of("image.close"), acquired); assertEquals(List.of("image.close"), previous);
    }
    @Test public void aFailureAfterInsertionLeavesTheNewImageOwnedUntilRingCleanup() {
        ZslFrameBuffer ring = new ZslFrameBuffer(); List<String> replacement = new ArrayList<>();
        int[] previousCloses = {0};
        ring.image(image(1, new ArrayList<String>() {
            @Override public boolean add(String event) {
                previousCloses[0]++; throw new OutOfMemoryError("synthetic replaced image close");
            }
        }));
        assertThrows(OutOfMemoryError.class, () -> ring.image(image(1, replacement)));
        assertTrue(replacement.isEmpty()); assertEquals(1, previousCloses[0]);
        ring.close(); ring.close();
        assertEquals(1, previousCloses[0]); assertEquals(List.of("image.close"), replacement);
    }
}
