package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

import org.junit.Test;

/**
 * The first review line said "P1 合格 判定情報なし" on hardware, claiming a pass
 * and denying one in the same breath.
 */
public class ReviewHeadlineTest {
    @Test
    public void recognisedTextNeverCertifiesTheWholePage() {
        PageFraming complete = PageFraming.builder(1920, 1080)
                .addLineBounds(200, 150, 1700, 200)
                .build();

        assertEquals("P1 文字枠のみ・紙面未確認",
                DocScanController.reviewHeadline(1, complete));
        assertEquals("P1 文字枠のみ・紙面未確認",
                DocScanController.reviewHeadline(1, PageFraming.fromToken("COMPLETE#1")));
    }

    @Test
    public void aClippedPageIsCalledAFailureAndNamesTheSide() {
        PageFraming clipped = PageFraming.builder(1920, 1080)
                .addLineBounds(200, 150, 1919, 200)
                .build();

        assertEquals("P2 不合格 右が切れています",
                DocScanController.reviewHeadline(2, clipped));
    }

    @Test
    public void anUnjudgeablePageClaimsNeitherVerdict() {
        String restored = DocScanController.reviewHeadline(1, PageFraming.UNKNOWN);
        String noText = DocScanController.reviewHeadline(
                1, PageFraming.builder(1920, 1080).build());

        assertEquals("P1 判定情報なし", restored);
        assertEquals("P1 文字が見つからず判定不可", noText);
        assertFalse(restored.contains("合格"));
        assertFalse(noText.contains("合格"));
    }
}
