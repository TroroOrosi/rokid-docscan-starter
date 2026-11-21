package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

import java.util.List;
import org.junit.Test;

/**
 * The controller's sentences were written for the phone relay. On the glasses they have to name the gesture that does
 * the thing today (ordinary reading, from 2026-11-12: a tap clears the display and stops the camera, the forward
 * swipe takes or retakes a photo, the double tap ends the capture; in an error only the double tap is taken, and two
 * of them leave). Until 2026-11-17 this map still said "タップで撮影準備", "前スワイプで完了" and "後スワイプで撮り直し".
 */
public class GlassesHudTextTest {
    @Test
    public void readyAndReadingNameTheGesturesOfOrdinaryReading() {
        assertEquals(List.of("準備完了", "前スワイプで撮影", "ダブルタップで終了"),
                GlassesHudText.adapt(List.of("準備完了", "撮影準備はスマホ", "読取完了はスマホ")));
        assertEquals(List.of("前スワイプで次・ダブルタップで終了"), GlassesHudText.adapt(List.of("次ページ / 完了はスマホ")));
    }

    @Test
    public void whereTheTapTakesThePhotoItIsStillTheTap() {
        // mixed English and listening keep the earlier assignment while capturing
        assertEquals(List.of("準備完了", "タップで撮影", "ダブルタップで終了"),
                GlassesHudText.adapt(List.of("準備完了", "撮影準備はスマホ", "読取完了はスマホ"), true));
    }

    @Test
    public void reviewNamesTheForwardSwipeForARetakeAndNoButton() {
        assertEquals(List.of("P1 構図確認のみ", "OCR 120文字・前スワイプで撮り直し", "無操作で保存"),
                GlassesHudText.adapt(List.of("P1 全体を確認", "OCR 120文字・確認はスマホ", "登録はスマホのボタン")));
        assertEquals(List.of("P2 上端欠け", "前スワイプで撮り直し", "OCR 90文字"),
                GlassesHudText.adapt(List.of("P2 上端欠け", "撮り直しはスマホ", "OCR 90文字")));
    }

    @Test
    public void anErrorSaysTheWayOutThatExists() {
        // In an error the glasses take the double tap only: two of them leave, and the reading is under 中断した読取.
        assertEquals(List.of("エラー", "カメラ状態が不明です", "ダブルタップ2回で終了→中断した読取から再開"),
                GlassesHudText.adapt(List.of("エラー", "カメラ状態が不明です", "スマホ画面を確認")));
        for (String told : List.of("Hi Rokid認可・再接続", "Hi Rokidを再接続", "Hi Rokidを再接続してください", "Hi Rokidを認可")) {
            String shown = GlassesHudText.adapt(List.of(told)).get(0);
            assertFalse(shown, shown.contains("Hi Rokid") || shown.contains("再起動"));
        }
    }

    @Test
    public void serverHintsAndErrorsNeverSendOperatorToPhone() {
        for (String line : GlassesHudText.adapt(List.of("操作はスマホ", "次ページ / 完了はスマホ", "スマホ画面を確認", "撮影準備はスマホ"))) {
            assertFalse(line.contains("スマホ"));
        }
        assertEquals(List.of("前後スワイプで移動"), GlassesHudText.adapt(List.of("操作はスマホ")));
    }

    @Test
    public void localReviewDoesNotClaimImageQualityOrCalibratedDistance() {
        assertEquals(List.of("P1 構図確認のみ", "無操作で保存・画質未検証", "距離と照明を確認"),
                GlassesHudText.adapt(List.of("P1 撮影確認", "無操作で確定", "40〜60cm離す")));
        assertEquals(List.of("距離と照明を確認・中心を＋へ"),
                GlassesHudText.adapt(List.of("40〜60cm・中心を＋へ")));
    }
}
