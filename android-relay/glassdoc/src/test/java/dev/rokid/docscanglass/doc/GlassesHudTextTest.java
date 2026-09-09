package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

import java.util.List;
import org.junit.Test;

public class GlassesHudTextTest {
    @Test
    public void readyAndReadingDescribeLocalGestures() {
        assertEquals(List.of("準備完了", "タップで撮影準備", "前スワイプで完了"),
                GlassesHudText.adapt(List.of("準備完了", "撮影準備はスマホ", "読取完了はスマホ")));
    }

    @Test
    public void reviewPreservesVerdictAndOffersRegistrationAndRetake() {
        assertEquals(List.of("P1 全体を確認", "OCR 120文字・後スワイプで撮り直し", "タップで登録"),
                GlassesHudText.adapt(List.of("P1 全体を確認", "OCR 120文字・確認はスマホ", "登録はスマホのボタン")));
        assertEquals(List.of("P2 上端欠け", "後スワイプで撮り直し", "OCR 90文字"),
                GlassesHudText.adapt(List.of("P2 上端欠け", "撮り直しはスマホ", "OCR 90文字")));
    }

    @Test
    public void serverHintsAndErrorsNeverSendOperatorToPhone() {
        for (String line : GlassesHudText.adapt(List.of("操作はスマホ", "次ページ / 完了はスマホ", "スマホ画面を確認"))) {
            assertFalse(line.contains("スマホ"));
        }
        assertEquals(List.of("前後スワイプで移動"), GlassesHudText.adapt(List.of("操作はスマホ")));
    }
}
