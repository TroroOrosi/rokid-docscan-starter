package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import java.util.Arrays;
import java.util.HexFormat;
import org.junit.Test;

public class PageChangeTest {
    // Nearest-neighbour 32x24 luminance from the original 4032x3024 capture:
    // data/device-setup/glassdoc-kokugo-20260927/originals/20260922-215900-capture-original.jpg
    // SHA256 b2174b90e5f14718f75c06468378dc29f734700d840501fd3607145918daf686.
    // At this resolution no exam text is readable; the dark paper/desk structure remains.
    private static byte[] photographedPage() {
        return HexFormat.of().parseHex("""
                0301060007474c484c48454a4f555453554e4c4e5a392c4124421d18151d0d04
                10010106014e494d41484e4d534854505252515850452c241d351a221f2b0909
                22150100054a464b45454e4a45324f343a414f525839271e243b352f1b220e05
                1c1d0a07070143404a484a43444945534e55524e4d432824271c4037340a0a0a
                2303130701004439433340304850544b4d5850524f292a201d27261a191e0207
                0b010906000246453f3e4b4944454e4455395a4e58472c21232a461c2e2a030c
                0508060506024642404743424c4135334447545552402e202a1d1d20182a1518
                0101080007004f44453d3f4a4643414a515349524c32293a262028271414170d
                050a020703034e3f443d45444949474a4a474d4b4f41113c25221a36200f0c0c
                0b01060900003f414243453e3a413e3b433c3b45452f2b2312153c38221a1812
                010101090a00504a3a3f3f473b3d473e49424a4d55422d2a24273e361d251b0a
                0101010109054147463c383a393b39443f434b4247140f22301f1e2721172111
                0801020208004e3f434337423c43423d3d4442494a232c24361b24191c240909
                080103010101013f414438454541373628444b4d4e3010211d3c1839201d0a05
                010705020101003c45354026450142393c47414b46262715380f171c1a190f00
                010101010804013b35313a26333c3e453c3a3644461e1729161d3432171e0c00
                05010601010101213839362e313e3b413244393f38121b221a241b12381a0f05
                01010101080e081d3433262e2c30353b39383e3e411b1722131c2a1212111803
                010107020a0a0a182a151c232b2c312a3e3b3f383f2c1b101c1b0e140a040e01
                0101010103010416232f3231252a2c212839363a132f31291334140f0b080a04
                02010d010a0d181a000308030e140b0d0e0e1719141f162f2531271a0f030604
                010201171b161d141e000001110a1d18151016181f201a12161c1f2b22100401
                020a090b1a1c1d251918050a0c170c0909050f1b1b20201a1616231b12100b08
                070b0801061c1e1d1c12090010121a15070520141a1e171d1115181810080903
                """.replaceAll("\\s", ""));
    }

    private byte[] frame(int value) {
        byte[] pixels = new byte[32 * 24];
        Arrays.fill(pixels, (byte) value);
        return pixels;
    }

    @Test public void oneStillPerTurnEvenWhenNextPageLooksLikePreviousPage() {
        PageChange change = new PageChange();
        byte[] page = frame(180);
        change.observe(page, 0);
        change.observe(page, 400);
        assertTrue(change.ready(400));
        change.consumed();
        change.observe(page, 1000);
        assertFalse(change.ready(1000));
        byte[] turning = frame(180);
        Arrays.fill(turning, 0, turning.length / 3, (byte) 70);
        change.observe(turning, 1300); // page turning during the photo review
        change.observe(page, 1500); // similar page: retain the observed turn
        change.observe(page, 1900);
        assertTrue(change.ready(1900));
        change.consumed();
        change.observe(page, 3000);
        assertFalse(change.ready(3000));
    }

    @Test public void smallExposureDriftDoesNotPretendThatThePageTurned() {
        PageChange change = new PageChange();
        change.observe(frame(180), 0);
        change.observe(frame(180), 400);
        change.consumed();
        change.observe(frame(183), 1000);
        change.observe(frame(183), 1500);
        assertFalse(change.ready(1500));
    }

    @Test public void positiveChangesHaveDistinctSequencesButOnlyQuietScenesBecomeCandidates() {
        PageChange change = new PageChange(); byte[] page = photographedPage();
        change.observe(page, 0); change.observe(page, 400);
        long initial = change.sequence(); change.consumed();
        byte[] brighter = page.clone();
        for (int i = 0; i < brighter.length; i++) brighter[i] = (byte)((brighter[i] & 255) + 15);
        change.observe(brighter, 600);
        assertEquals("gain alone does not create scene identity", initial, change.sequence());
        byte[] turning = page.clone(); Arrays.fill(turning, 0, turning.length / 3, (byte)160);
        change.observe(turning, 800);
        long moving = change.sequence(); assertTrue(moving > initial); assertFalse(change.ready(1000));
        change.observe(page, 1000); assertTrue(change.sequence() > moving);
        assertFalse("positive motion is not a stable-page assertion", change.ready(1399));
        assertTrue(change.ready(1400)); change.consumed();
        change.observe(turning, 1500); change.observe(page, 1600); assertTrue(change.ready(2000));
        assertTrue("A to B to A retains separate positive observations", change.sequence() > moving + 1);
    }

    @Test public void wholeFrameExposureStepDoesNotCaptureTheSamePhotographedPageAgain() {
        PageChange change = new PageChange();
        byte[] page = photographedPage();
        change.observe(page, 0);
        change.observe(page, 400);
        change.consumed();
        byte[] brighter = page.clone();
        for (int i = 0; i < brighter.length; i++) brighter[i] = (byte) ((brighter[i] & 255) + 30);
        change.observe(brighter, 1000);
        change.observe(brighter, 1500);
        assertFalse("a uniform exposure change is not a new page", change.ready(1500));
        change.observe(page, 1800);
        change.observe(page, 2300);
        assertFalse("returning exposure is not a page turn either", change.ready(2300));
    }

    @Test public void anObservedTurnSurvivesReuseOfThePreviewBufferAndASimilarNextPage() {
        PageChange change = new PageChange();
        byte[] page = photographedPage();
        byte[] reusable = page.clone();
        change.observe(reusable, 0);
        change.observe(reusable, 400);
        change.consumed();
        for (int y = 0; y < 24; y++) for (int x = 0; x < 12; x++) reusable[y * 32 + x] = (byte) 160;
        change.observe(reusable, 1000); // turning paper covers part of the frame
        assertFalse(change.ready(1200));
        System.arraycopy(page, 0, reusable, 0, page.length);
        change.observe(reusable, 1300); // the next page has the same coarse appearance
        change.observe(reusable, 1700);
        assertTrue("the transient turn must remain latched", change.ready(1700));
        change.consumed();
        change.observe(reusable, 2500);
        assertFalse("the same page may only yield one still", change.ready(2500));
    }

    @Test public void aSlowTurnAccumulatesAcrossSmallAdjacentFrameChanges() {
        PageChange change = new PageChange();
        byte[] page = photographedPage();
        change.observe(page, 0);
        change.observe(page, 400);
        change.consumed();
        long capturedScene = change.sequence();
        byte[] turning = page.clone();
        for (int x = 0; x < 12; x++) {
            for (int y = 0; y < 24; y++) turning[y * 32 + x] = (byte) 160;
            change.observe(turning, 1000 + x * 50);
        }
        change.observe(turning, 2000);
        assertTrue("one-column steps must not erase the cumulative turn", change.sequence() > capturedScene);
        assertTrue("the changed scene is ready after settling", change.ready(2000));
        change.consumed();
        change.observe(turning, 2500);
        assertFalse("a retained scene yields only one still", change.ready(2500));
    }

    @Test public void samePageOnePixelJitterDoesNotAccumulateIntoATurn() {
        PageChange change = new PageChange();
        byte[] page = photographedPage();
        change.observe(page, 0);
        change.observe(page, 400);
        change.consumed();
        long capturedScene = change.sequence();
        for (int observation = 0; observation < 20; observation++) {
            int offset = observation % 2 == 0 ? 1 : -1;
            byte[] shifted = new byte[page.length];
            for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) {
                shifted[y * 32 + x] = page[y * 32 + Math.max(0, Math.min(31, x + offset))];
            }
            change.observe(shifted, 1000 + observation * 50);
        }
        change.observe(page, 2500);
        assertEquals("bounded head jitter is not positive page evidence", capturedScene, change.sequence());
        assertFalse(change.ready(2500));
    }

    @Test public void gradualUniformExposureDriftDoesNotAccumulateIntoATurn() {
        PageChange change = new PageChange();
        byte[] page = photographedPage();
        change.observe(page, 0);
        change.observe(page, 400);
        change.consumed();
        long capturedScene = change.sequence();
        for (int gain = 1; gain <= 30; gain++) {
            byte[] brighter = page.clone();
            for (int i = 0; i < brighter.length; i++) brighter[i] = (byte) ((brighter[i] & 255) + gain);
            change.observe(brighter, 1000 + gain * 50);
        }
        change.observe(page, 3000);
        assertEquals("uniform gain does not create a scene", capturedScene, change.sequence());
        assertFalse(change.ready(3000));
    }

    @Test public void consumingUsesTheLatestPreviewRatherThanOldSubthresholdDrift() {
        PageChange change = new PageChange();
        byte[] page = photographedPage();
        change.observe(page, 0);
        for (int y = 0; y < 24; y++) for (int x = 0; x < 2; x++) page[y * 32 + x] = (byte) 160;
        change.observe(page, 400);
        change.consumed();
        long capturedScene = change.sequence();
        for (int y = 0; y < 24; y++) for (int x = 2; x < 4; x++) page[y * 32 + x] = (byte) 160;
        change.observe(page, 1000);
        change.observe(page, 1500);
        assertEquals("pre-shutter drift must not be counted again", capturedScene, change.sequence());
        assertFalse(change.ready(1500));
    }

    private byte[] shifted(byte[] page, int dx, int dy) {
        byte[] result = new byte[page.length];
        for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) {
            result[y * 32 + x] = page[Math.max(0, Math.min(23, y + dy)) * 32
                    + Math.max(0, Math.min(31, x + dx))];
        }
        return result;
    }

    @Test public void samePageJitterDoesNotDependOnWhichPhaseWasPhotographed() {
        byte[] page = photographedPage();
        for (int capturedX = -1; capturedX <= 1; capturedX++) for (int capturedY = -1; capturedY <= 1; capturedY++) {
            PageChange change = new PageChange();
            byte[] captured = shifted(page, capturedX, capturedY);
            change.observe(captured, 0);
            change.observe(captured, 400);
            change.consumed();
            long capturedScene = change.sequence();
            for (int observation = 0; observation < 18; observation++) {
                int dx = observation % 3 - 1;
                int dy = observation / 3 % 3 - 1;
                change.observe(shifted(page, dx, dy), 1000 + observation * 50);
            }
            change.observe(captured, 2500);
            assertEquals("same-page jitter from capture phase " + capturedX + "," + capturedY,
                    capturedScene, change.sequence());
            assertFalse(change.ready(2500));
        }
    }

    @Test public void unconsumedMotionStillWaitsAfterATranslation() {
        PageChange motion = new PageChange();
        byte[] page = photographedPage();
        motion.observe(shifted(page, -1, 0), 0);
        motion.observe(shifted(page, -1, 0), 400);
        assertTrue(motion.ready(400));
        motion.observe(shifted(page, 1, 0), 1000);
        assertFalse("preview motion is not exempted by page-jitter compensation", motion.ready(1000));
        assertFalse(motion.ready(1399));
        assertTrue(motion.ready(1400));
    }

    @Test public void aSlowOuterTurnStillRetainsASimilarFollowingPage() {
        PageChange change = new PageChange();
        byte[] page = photographedPage();
        change.observe(page, 0);
        change.observe(page, 400);
        change.consumed();
        long capturedScene = change.sequence();
        byte[] turning = page.clone();
        for (int x = 31; x >= 20; x--) {
            for (int y = 0; y < 24; y++) turning[y * 32 + x] = (byte) 160;
            change.observe(turning, 1000 + (31 - x) * 50);
        }
        assertTrue("right-edge turn evidence must survive registration", change.sequence() > capturedScene);
        change.observe(page, 1700);
        assertFalse(change.ready(2099));
        assertTrue("a similar A-B-A return still follows an observed turn", change.ready(2100));
        change.consumed();
        change.observe(page, 2600);
        assertFalse(change.ready(2600));
    }
}
