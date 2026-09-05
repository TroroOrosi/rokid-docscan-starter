package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.List;
import org.junit.Test;

public class HudLayoutTest {
    @Test
    public void limitsDisplayToThreeLinesAndEscapesJson() {
        String json = HudLayout.fromLines(List.of("問\"1", "A\\B", "3", "ignored"));
        assertTrue(json.contains("問\\\"1\\nA\\\\B\\n3"));
        assertFalse(json.contains("ignored"));
        assertTrue(json.contains("\"id\":\"docscan_root\""));
        assertTrue(json.contains("\"layout_width\":\"match_parent\""));
        assertTrue(json.contains("\"layout_height\":\"match_parent\""));
        assertTrue(json.contains("\"textSize\":\"34sp\""));
        assertFalse(json.contains("\"width\":"));
        assertFalse(json.contains("\"height\":"));
    }

    @Test
    public void captureReviewUsesAPresentIconAndSafeGlassesActions() {
        String json = HudLayout.fromCaptureReview(
                "docscan_preview",
                List.of("P2 未登録 / OCR 0文字", "確認と操作はスマホ", "登録はスマホのボタン"));

        assertTrue(json.contains("\"type\":\"ImageView\""));
        assertTrue(json.contains("\"name\":\"docscan_preview\""));
        assertTrue(json.contains("\"scaleType\":\"fit_center\""));
        assertTrue(json.contains("確認と操作はスマホ"));
        assertFalse(json.contains("タップ"));
        assertTrue(json.contains("登録はスマホのボタン"));
    }

    @Test
    public void aimingGuideShowsAFrameDistanceAndManualShutter() {
        String json = HudLayout.fromCaptureAiming(2, true);

        assertTrue(json.contains("P2を撮り直し"));
        assertTrue(json.contains("40〜60cm"));
        assertTrue(json.contains("四隅"));
        assertTrue(json.contains("シャッターはスマホ"));
        assertFalse(json.contains("タップ"));
        assertTrue(json.contains("＋"));
    }
}
