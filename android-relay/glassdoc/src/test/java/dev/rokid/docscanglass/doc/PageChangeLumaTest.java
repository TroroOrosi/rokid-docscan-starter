package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import java.nio.ByteBuffer;
import java.util.Arrays;
import org.junit.Test;

public class PageChangeLumaTest {
    static byte[] glyph(boolean other) {
        byte[] p = new byte[320 * 240]; Arrays.fill(p, (byte)235);
        String[] g = other ? new String[]{"00100","01100","00100","00100","00100","00100","01110"}
                : new String[]{"01110","11011","11011","11011","11011","11011","01110"};
        for (int cy=0; cy<23; cy++) for (int cx=0; cx<31; cx++)
            for (int y=0; y<7; y++) for (int x=0; x<5; x++)
                if (g[y].charAt(x)=='1') p[(cy*10+y+1)*320+cx*10+x+1]=30;
        return p;
    }
    static byte[] coarse(byte[] p) {
        byte[] small=new byte[768];
        for(int y=0;y<24;y++) for(int x=0;x<32;x++) small[y*32+x]=p[y*10*320+x*10];
        return small;
    }
    static void frame(PageChange page, byte[] p, long now) {
        page.observeFrame(coarse(p), ByteBuffer.wrap(p), 320, 240, 320, 1, (now+1)*1_000_000L, now);
    }
    private PageChange consumed(byte[] p) {
        PageChange page=new PageChange(); frame(page,p,0);frame(page,p,400);
        assertTrue(page.ready(400)); assertTrue(page.fineMotionReady(400));page.consumed();return page;
    }
    static byte[] shift(byte[] p,int dx,int dy) {
        byte[] out=new byte[p.length];
        for(int y=0;y<240;y++)for(int x=0;x<320;x++)
            out[y*320+x]=p[Math.max(0,Math.min(239,y+dy))*320+Math.max(0,Math.min(319,x+dx))];
        return out;
    }
    @Test public void expiredOrInterruptedSearchNeverPublishesAPartialPositive() {
        java.util.concurrent.atomic.AtomicLong clock = new java.util.concurrent.atomic.AtomicLong();
        LumaPageEvidence e = new LumaPageEvidence(() -> clock.getAndAdd(20_000_000));
        byte[] a = new byte[320 * 240], b = a.clone();
        for (int y = 0; y < 240; y++) for (int x = 0; x < 320; x++)
            b[y * 320 + x] = (byte)((x / 5 + y / 5) % 2 == 0 ? 235 : 160);
        e.sample(ByteBuffer.wrap(a), 320, 240, 320, 1, 0); e.acceptScene();
        e.sample(ByteBuffer.wrap(b), 320, 240, 320, 1, 1000);
        assertFalse(e.changed(true, 1000));
        assertEquals("time_budget", e.status());
        assertTrue(e.evaluatedOffsets() < 1681);
        Thread.currentThread().interrupt();
        try {
            assertFalse(e.changed(true, 2000));
            assertEquals("interrupted", e.status());
            assertEquals(0, e.evaluatedOffsets());
        } finally { Thread.interrupted(); }
    }

    @Test public void stableGeometryReusesTheTwoIntegralBuffersAtPreviewFrequency() throws Exception {
        LumaPageEvidence e = new LumaPageEvidence();
        byte[] a = new byte[320 * 240];
        e.sample(ByteBuffer.wrap(a), 320, 240, 320, 1, 0); e.acceptScene();
        java.lang.reflect.Field first = LumaPageEvidence.class.getDeclaredField("first");
        java.lang.reflect.Field second = LumaPageEvidence.class.getDeclaredField("second");
        first.setAccessible(true); second.setAccessible(true);
        Object f = first.get(e), g = second.get(e);
        for (int i = 1; i <= 20; i++) e.sample(ByteBuffer.wrap(a), 320, 240, 320, 1, i * 10);
        assertSame(f, first.get(e)); assertSame(g, second.get(e));
        assertTrue(e.retainedIntegralInts() * 4 < 1_000_000);
    }

    @Test public void glyphsBetweenPointsBecomeOnePageAndStillWaitForUncompensatedStillness() {
        byte[] a=glyph(false), b=glyph(true);assertArrayEquals(coarse(a),coarse(b));
        PageChange p=consumed(a);long before=p.sequence();frame(p,b,1000);
        assertTrue(p.sequence()>before);assertFalse(p.ready(1399));assertFalse(p.fineMotionReady(1399));
        frame(p,b,1400);assertTrue(p.ready(1400));assertTrue(p.fineMotionReady(1400));p.consumed();
        frame(p,b,2000);frame(p,b,2500);assertFalse(p.ready(2500));
    }
    @Test public void aLocalizedSixthChangesButTwoColumnDriftRemainsBelowTheEvidenceFloor() {
        byte[] a=new byte[320*240];Arrays.fill(a,(byte)220);PageChange p=consumed(a);
        byte[] b=a.clone();Arrays.fill(b,80*320,120*320,(byte)160);frame(p,b,1000);frame(p,b,1400);
        assertTrue(p.ready(1400));p.consumed();frame(p,b,2000);assertFalse(p.ready(2000));
        PageChange drift=new PageChange();frame(drift,a,0);
        for(int y=0;y<240;y++)Arrays.fill(a,y*320,y*320+20,(byte)160);
        frame(drift,a,400);drift.consumed();long scene=drift.sequence();
        for(int y=0;y<240;y++)Arrays.fill(a,y*320+20,y*320+40,(byte)160);
        frame(drift,a,1000);frame(drift,a,1500);assertEquals(scene,drift.sequence());
        assertFalse(drift.ready(1500));
    }
    @Test public void nativeOnePixelJitterDoesNotTurnThePageButRestartsTheMotionWait() {
        byte[] a=glyph(false);PageChange p=consumed(a);long scene=p.sequence();
        byte[] jitter=shift(a,1,1);frame(p,jitter,1000);
        assertEquals(scene,p.sequence());assertFalse(p.ready(1000));assertFalse(p.fineMotionReady(1000));
        frame(p,jitter,1200);assertFalse(p.fineMotionReady(1399));assertTrue(p.fineMotionReady(1400));
        frame(p,a,1500);assertEquals(scene,p.sequence());assertFalse(p.fineMotionReady(1500));
    }
    @Test public void allNativeJitterPhasesKeepOnePageWithoutCompensatingMotion() {
        byte[] a=glyph(false);PageChange p=consumed(shift(a,-1,-1));long scene=p.sequence();
        int[][] phases={{0,0},{1,1},{-1,1},{1,-1},{-1,-1},{0,1}};
        for(int i=0;i<phases.length;i++) {
            frame(p,shift(a,phases[i][0],phases[i][1]),1000+i*250);
            assertEquals("one coherent integer-pixel registration",scene,p.sequence());
        }
        assertFalse(p.ready(3000));
    }
    @Test public void uniformExposureDriftDoesNotCreateFinePageOrMotionEvidence() {
        byte[] a=glyph(false),b=a.clone();PageChange p=consumed(a);long scene=p.sequence();
        for(int i=0;i<b.length;i++)b[i]=(byte)((b[i]&255)+15);
        frame(p,b,1000);assertEquals(scene,p.sequence());assertTrue(p.fineMotionReady(1000));
        frame(p,a,1500);assertEquals(scene,p.sequence());assertFalse(p.ready(1500));
    }
    @Test public void detailOnlyNativeMotionCannotBorrowTheBaseGridsQuietWindow() {
        byte[] a = new byte[320 * 240], b = a.clone();
        for (int y = 0; y < 240; y++) for (int x = 0; x < 320; x++) a[y * 320 + x] = (byte)(x % 5 < 2 ? 20 : 220);
        b = shift(a, 1, 0); assertArrayEquals(coarse(a), coarse(b));
        PageChange page = consumed(a); long scene = page.sequence(); frame(page, b, 1000);
        assertEquals(scene, page.sequence()); assertFalse(page.fineMotionReady(1000));
        frame(page, b, 1400); assertTrue(page.fineMotionReady(1400));
    }

    @Test public void paddingPixelStrideAndBufferOriginDoNotBecomePageContent() {
        byte[] a=glyph(false),storage=new byte[7+647*240];Arrays.fill(storage,(byte)9);
        for(int y=0;y<240;y++)for(int x=0;x<320;x++)storage[7+y*647+x*2]=a[y*320+x];
        ByteBuffer padded=ByteBuffer.wrap(storage);padded.position(7);PageChange p=consumed(a);
        long scene=p.sequence();p.observeFrame(coarse(a),padded,320,240,647,2,1_001_000_000L,1000);
        assertEquals(7,padded.position());assertEquals(scene,p.sequence());assertTrue(p.fineMotionReady(1000));
    }
    @Test public void unknownOrStaleFramesCannotRefreshStillnessOrInventATurn() {
        byte[] a=glyph(false);PageChange p=consumed(a);long scene=p.sequence();
        p.observeFrame(coarse(glyph(true)),ByteBuffer.wrap(a),320,240,320,1,1,1000);
        assertEquals(scene,p.sequence());assertEquals("stale_frame",p.fineStatus());assertFalse(p.fineMotionReady(1000));
        frame(p,a,1500);assertFalse("unknown interval needs a new quiet window",p.fineMotionReady(1500));
        frame(p,a,1900);assertTrue(p.fineMotionReady(1900));
        p.observeFrame(coarse(a),ByteBuffer.allocate(10),320,240,320,1,2_001_000_000L,2000);
        assertEquals("invalid_plane",p.fineStatus());assertFalse(p.fineMotionReady(2000));
    }
    @Test public void largeCommonStreamsFallBackExplicitlyWithoutAllocatingFineStorage() {
        LumaPageEvidence f=new LumaPageEvidence();
        assertTrue(f.sample(null,1280,960,1280,1,0));assertEquals("size_budget",f.status());
        assertEquals(0,f.retainedIntegralInts());assertTrue(f.motionReady(0));assertFalse(f.changed(true,1000));
        assertTrue(f.sample(null,1024,768,1024,1,0));assertEquals("offset_budget",f.status());
        assertEquals(0,f.retainedIntegralInts());assertFalse(f.changed(true,1000));
    }
    @Test public void positiveRegistrationCompletesEveryOffsetAndExpensiveWorkIsThrottled() {
        LumaPageEvidence f=new LumaPageEvidence();byte[] a=glyph(false),b=glyph(true);
        assertTrue(f.sample(ByteBuffer.wrap(a),320,240,320,1,0));f.acceptScene();
        assertTrue(f.sample(ByteBuffer.wrap(b),320,240,320,1,1000));assertTrue(f.changed(true,1000));
        assertEquals(1681,f.evaluatedOffsets());assertTrue(f.evaluatedOffsets()<=LumaPageEvidence.MAX_OFFSETS);
        assertTrue(f.retainedIntegralInts()*4<=2_110_000);
        f.sample(ByteBuffer.wrap(b),320,240,320,1,1100);assertFalse(f.changed(true,1100));
        assertEquals(0,f.evaluatedOffsets());assertEquals("throttled",f.status());
    }
    static byte[] scaledGlyph(boolean other) {
        byte[] small = glyph(other), out = new byte[640 * 480];
        for (int y = 0; y < 480; y++) for (int x = 0; x < 640; x++) out[y * 640 + x] = small[(y / 2) * 320 + x / 2];
        return out;
    }
    static byte[] coarse640(byte[] p) {
        byte[] out = new byte[768];
        for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) out[y * 32 + x] = p[y * 20 * 640 + x * 20];
        return out;
    }
    private static void frame640(PageChange page, byte[] pixels, long now) {
        page.observeFrame(coarse640(pixels), ByteBuffer.wrap(pixels), 640, 480, 640, 1, (now + 1) * 1_000_000, now);
    }
    @Test public void both640GlyphDirectionsAndABARequireAll6561CoherentOffsets() {
        byte[] a = scaledGlyph(false), b = scaledGlyph(true); assertArrayEquals(coarse640(a), coarse640(b));
        for (byte[][] pair : new byte[][][]{new byte[][]{a, b}, new byte[][]{b, a}}) {
            LumaPageEvidence e = new LumaPageEvidence(() -> 0);
            e.sample(ByteBuffer.wrap(pair[0]), 640, 480, 640, 1, 0); e.acceptScene();
            e.sample(ByteBuffer.wrap(pair[1]), 640, 480, 640, 1, 1000);
            assertTrue(e.changed(true, 1000)); assertEquals(6561, e.evaluatedOffsets());
        }
        PageChange page = new PageChange(); frame640(page, a, 0); frame640(page, a, 400); page.consumed();
        long initial = page.sequence();
        for (int i = 0; i < 8; i++) frame640(page, b, 1000 + i * 200);
        assertTrue(page.sequence() > initial); page.consumed(); long middle = page.sequence();
        for (int i = 0; i < 8; i++) frame640(page, a, 3000 + i * 200);
        assertTrue(page.sequence() > middle);
    }
    @Test public void fine640PhaseJitterAndExposurePreservePageButNotAnUncompensatedMotionShortcut() {
        byte[] a = scaledGlyph(false), jitter = a.clone(), gain = a.clone();
        for (int y = 0; y < 480; y++) for (int x = 0; x < 640; x++)
            jitter[y * 640 + x] = a[Math.min(479, y + 1) * 640 + Math.min(639, x + 1)];
        for (int i = 0; i < gain.length; i++) gain[i] = (byte)((a[i] & 255) + 15);
        PageChange page = new PageChange(); frame640(page, a, 0); frame640(page, a, 400); page.consumed();
        long scene = page.sequence(); frame640(page, jitter, 1000);
        assertEquals(scene, page.sequence()); assertFalse(page.fineMotionReady(1000));
        frame640(page, jitter, 1400); assertTrue(page.fineMotionReady(1400));
        frame640(page, a, 2000); frame640(page, a, 2400);
        frame640(page, gain, 3000); assertEquals(scene, page.sequence()); assertTrue(page.fineMotionReady(3000));
        page.observeFrame(coarse640(a), ByteBuffer.wrap(a), 640, 480, 640, 1, 1, 3100);
        assertEquals("stale_frame", page.fineStatus()); assertFalse(page.fineMotionReady(3100));
    }
    @Test public void localized640ChangeAndNearCapAllocationsRemainBounded() {
        byte[] a = new byte[640 * 480]; Arrays.fill(a, (byte)220); byte[] b = a.clone();
        Arrays.fill(b, 160 * 640, 240 * 640, (byte)160);
        LumaPageEvidence e = new LumaPageEvidence(() -> 0);
        e.sample(ByteBuffer.wrap(a), 640, 480, 640, 1, 0); e.acceptScene();
        e.sample(ByteBuffer.wrap(b), 640, 480, 640, 1, 1000); assertTrue(e.changed(true, 1000));
        byte[] max = new byte[800 * 480]; e.sample(ByteBuffer.wrap(max), 800, 480, 800, 1, 2000);
        assertEquals(4_043_688, e.retainedIntegralInts() * 4);
        assertTrue(e.retainedArrayBytes() <= 4_216_000);
        e.sample(ByteBuffer.wrap(max), 64, 48, 800, 1, 3000);
        assertEquals("size_budget", e.status()); assertEquals(0, e.retainedIntegralInts());
    }

    @Test public void latestPreShutterFineContentBecomesTheCapturedReferenceEvenDuringThrottle() {
        byte[] a=glyph(false),b=glyph(true);PageChange p=consumed(a);
        frame(p,a,1000);frame(p,b,1100); // expensive registration is throttled; latest frame must still be retained.
        p.consumed();long scene=p.sequence();frame(p,b,1500);assertEquals(scene,p.sequence());
        assertFalse(p.ready(1500));
    }

    static byte[] denseNative() {
        byte[] p = new byte[320 * 240]; long random = 0x7f1a9d3c5b82640eL;
        for (int i = 0; i < p.length; i++) {
            random ^= random << 13; random ^= random >>> 7; random ^= random << 17;
            p[i] = (byte)((random & 1) == 0 ? 24 : 230);
        }
        return p;
    }
    private static PageChange controlledPage(java.util.function.LongSupplier nanos) throws Exception {
        PageChange page = new PageChange();
        java.lang.reflect.Field fine = PageChange.class.getDeclaredField("fine"); fine.setAccessible(true);
        fine.set(page, new LumaPageEvidence(nanos)); return page;
    }
    private static PageChange controlledConsumed(byte[] pixels, java.util.function.LongSupplier nanos) throws Exception {
        PageChange page = controlledPage(nanos); frame(page, pixels, 0); frame(page, pixels, 400);
        page.consumed(); return page;
    }
    @Test public void all24DenseNativePhasesKeepTheCapturedPageWithoutBorrowingStillness() throws Exception {
        byte[] a = denseNative();
        for (int dy = -2; dy <= 2; dy++) for (int dx = -2; dx <= 2; dx++) {
            if (dx == 0 && dy == 0) continue;
            PageChange page = controlledConsumed(a, () -> 0); long scene = page.sequence();
            byte[] b = shift(a, dx, dy); frame(page, b, 1000);
            assertEquals("native phase " + dx + "," + dy, scene, page.sequence());
            assertFalse(page.ready(1400)); assertFalse(page.fineMotionReady(1399));
            frame(page, b, 1400); assertTrue(page.fineMotionReady(1400));
        }
    }
    @Test public void nativePhaseRescueNeverCompensatesAnUnconsumedPreview() throws Exception {
        byte[] a = denseNative(); PageChange page = controlledPage(() -> 0);
        frame(page, a, 0); frame(page, a, 400); long scene = page.sequence();
        frame(page, shift(a, 1, 0), 1000);
        assertEquals(scene + 1, page.sequence()); assertFalse(page.ready(1399)); assertTrue(page.ready(1400));
    }
    @Test public void nativePhaseUsesOneWholeFrameExposureCorrectionNotTheCoarseSampleMean() throws Exception {
        byte[] a = denseNative(), gain = shift(a, 1, 0);
        for (int i = 0; i < gain.length; i++) gain[i] = (byte)((gain[i] & 255) + 15);
        PageChange page = controlledConsumed(a, () -> 0); long scene = page.sequence();
        frame(page, gain, 1000); assertEquals(scene, page.sequence());
        // 10% sparse coarse outliers move the coarse sample mean by >18 but not the native mean.
        byte[] blank = new byte[320 * 240], sparse = blank.clone();
        for (int i = 0; i < 77; i++) sparse[(i / 32) * 10 * 320 + (i % 32) * 10] = (byte)255;
        page = controlledConsumed(blank, () -> 0); scene = page.sequence(); frame(page, sparse, 1000);
        assertEquals(scene + 1, page.sequence());
    }
    @Test public void coarseOnlyInkAndZeroSumChangesSurviveEvenWhenFineMeansAreSame() throws Exception {
        byte[] blank = new byte[320 * 240]; Arrays.fill(blank, (byte)128); byte[] zeroSum = blank.clone();
        for (int y = 0; y < 96; y++) for (int x = 0; x < 128; x++) {
            int at = y * 240 / 96 * 320 + x * 320 / 128;
            int sign = ((x * 13 + y * 7) & 4) == 0 ? 60 : -60;
            zeroSum[at] = (byte)(128 + sign); zeroSum[at + 1] = (byte)(128 - sign);
        }
        byte[] white = new byte[320 * 240]; Arrays.fill(white, (byte)220); byte[] ink = white.clone();
        for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++)
            if ((x + y) % 2 == 0) ink[y * 10 * 320 + x * 10] = 20;
        for (byte[][] pair : new byte[][][]{new byte[][]{blank, zeroSum}, new byte[][]{white, ink}}) {
            LumaPageEvidence fine = new LumaPageEvidence(() -> 0);
            fine.sample(ByteBuffer.wrap(pair[0]), 320, 240, 320, 1, 0); fine.acceptScene();
            fine.sample(ByteBuffer.wrap(pair[1]), 320, 240, 320, 1, 1000);
            assertFalse("control: both mean scales call this same", fine.changed(true, 1000));
            PageChange page = controlledConsumed(pair[0], () -> 0); long scene = page.sequence();
            frame(page, pair[1], 1000); assertEquals(scene + 1, page.sequence());
            assertFalse(page.ready(1399)); assertTrue(page.ready(1400));
        }
    }
    private static LumaPageEvidence phaseEvidence(byte[] a, byte[] b, java.util.function.LongSupplier nanos) {
        LumaPageEvidence fine = new LumaPageEvidence(nanos);
        fine.sample(ByteBuffer.wrap(a), 320, 240, 320, 1, 0); fine.acceptScene();
        fine.sample(ByteBuffer.wrap(b), 320, 240, 320, 1, 1000); return fine;
    }
    @Test public void nativePhaseMustMatchEveryDetailCellEvenWhenCoarsePointsAndBaseMeansAgree() {
        byte[] a = denseNative(), b = shift(a, 1, 0), changed = b.clone();
        // Within one 5x5 base cell, add 20 to its 3x3 detail cell and subtract it from nine other pixels.
        // Neither the base-cell sum, whole-frame sum nor any coarse point changes.
        for (int y = 2; y < 5; y++) for (int x = 2; x < 5; x++) changed[y * 320 + x] += 20;
        int left = 9;
        for (int y = 0; y < 5; y++) for (int x = 0; x < 5; x++) {
            if (left > 0 && !(x == 0 && y == 0) && (x < 2 || y < 2)) {
                changed[y * 320 + x] -= 20; left--;
            }
        }
        assertEquals(0, left); assertArrayEquals(coarse(b), coarse(changed));
        assertTrue(phaseEvidence(a, b, () -> 0).sameNativePhase(coarse(b)));
        assertFalse(phaseEvidence(a, changed, () -> 0).sameNativePhase(coarse(changed)));
    }
    @Test public void unknownNativePhaseCannotVetoAnOtherwisePositiveCoarsePage() throws Exception {
        byte[] a = denseNative(), b = shift(a, 1, 0);
        for (int mode = 0; mode < 3; mode++) {
            java.util.concurrent.atomic.AtomicLong nanos = new java.util.concurrent.atomic.AtomicLong();
            PageChange page = controlledConsumed(a, mode == 1 ? () -> nanos.getAndAdd(1_000_000) : () -> 0);
            long scene = page.sequence(); byte[] points = coarse(b);
            if (mode == 0) points[0] ^= 127; // Not the supplied native plane's origin/content.
            if (mode == 2) Thread.currentThread().interrupt();
            try {
                page.observeFrame(points, ByteBuffer.wrap(b), 320, 240, 320, 1, 1_001_000_000L, 1000);
                assertEquals(scene + 1, page.sequence()); assertFalse(page.ready(1399)); assertTrue(page.ready(1400));
                if (mode == 1) assertEquals("time_budget", page.fineStatus());
                if (mode == 2) assertEquals("interrupted", page.fineStatus());
            } finally { if (mode == 2) Thread.interrupted(); }
        }
        LumaPageEvidence unknown = new LumaPageEvidence(() -> 0);
        assertFalse(unknown.sameNativePhase(coarse(b)));
        assertFalse(unknown.sample(ByteBuffer.allocate(10), 320, 240, 320, 1, 1000));
        assertFalse(unknown.sameNativePhase(coarse(b))); assertEquals("invalid_plane", unknown.status());
    }
    @Test public void nativePhaseBudgetIncludesRowsAndTheFinalSameAcceptance() {
        byte[] a = denseNative(), b = shift(a, 1, 0);
        java.util.concurrent.atomic.AtomicLong calls = new java.util.concurrent.atomic.AtomicLong();
        LumaPageEvidence fine = phaseEvidence(a, b, () -> { calls.incrementAndGet(); return 0; });
        assertTrue(fine.sameNativePhase(coarse(b))); long completeCalls = calls.get(); assertTrue(completeCalls > 24);
        for (long expireAt : new long[]{4, completeCalls}) {
            calls.set(0);
            fine = phaseEvidence(a, b, () -> calls.incrementAndGet() >= expireAt ? 4_000_000 : 0);
            assertFalse(fine.sameNativePhase(coarse(b))); assertEquals("time_budget", fine.status());
            assertEquals(expireAt, calls.get());
        }
        calls.set(0); fine = phaseEvidence(a, b, () -> calls.getAndIncrement() == 0 ? 0 : -1);
        assertFalse(fine.sameNativePhase(coarse(b))); assertEquals("time_budget", fine.status());
    }
    @Test public void clampedCapturedEdgesMayConservativelyRefuseAnInRangeNativePhase() {
        byte[] a = denseNative(); int matches = 0, refused = 0;
        for (int ay = -1; ay <= 1; ay++) for (int ax = -1; ax <= 1; ax++)
            for (int by = -1; by <= 1; by++) for (int bx = -1; bx <= 1; bx++) {
                if (ax == bx && ay == by) continue;
                assertTrue(Math.max(Math.abs(bx - ax), Math.abs(by - ay)) <= 2);
                byte[] reference = shift(a, ax, ay), latest = shift(a, bx, by);
                if (phaseEvidence(reference, latest, () -> 0).sameNativePhase(coarse(latest))) matches++;
                else {
                    refused++;
                    PageChange page;
                    try { page = controlledConsumed(reference, () -> 0); }
                    catch (Exception reflectionFailure) { throw new AssertionError(reflectionFailure); }
                    long scene = page.sequence(); frame(page, latest, 1000);
                    assertEquals("lost edge support must not suppress coarse positive", scene + 1, page.sequence());
                }
            }
        assertEquals(16, matches); assertEquals(56, refused);
    }
}
