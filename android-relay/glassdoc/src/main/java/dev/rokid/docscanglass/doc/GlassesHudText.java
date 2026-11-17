package dev.rokid.docscanglass.doc;

import java.util.ArrayList;
import java.util.List;

/**
 * The controller's sentences, written for the phone relay, in the words of the glasses' own gestures.
 *
 * <p>Ordinary reading since 2026-11-12: a tap clears the display and stops the camera, the forward swipe takes a
 * photo or retakes one under review, no input for three seconds saves it, the double tap ends the capture. In an
 * error the glasses take the double tap only, two of them leave the app, and the reading is then under
 * 中断した読取. Until 2026-11-17 this map named the gestures of the build before that ("タップで撮影準備",
 * "前スワイプで完了", "後スワイプで撮り直し") and sent the wearer of an error to settings that the glasses do not
 * have.</p>
 */
final class GlassesHudText {
    private static final String WAY_OUT = "ダブルタップ2回で終了→中断した読取から再開";

    private GlassesHudText() {
    }

    static List<String> adapt(List<String> lines) {
        return adapt(lines, false);
    }

    /** tapShoots: mixed English and listening, where the tap still takes the photo while capturing. */
    static List<String> adapt(List<String> lines, boolean tapShoots) {
        String shoot = tapShoots ? "タップで撮影" : "前スワイプで撮影";
        List<String> adapted = new ArrayList<>(lines.size());
        for (String line : lines) {
            adapted.add((line == null ? "" : line)
                    .replace("撮影確認", "構図確認のみ")
                    .replace("全体を確認", "構図確認のみ")
                    .replace("無操作で確定", "無操作で保存・画質未検証")
                    .replace("40〜60cm離す", "距離と照明を確認")
                    .replace("40〜60cm", "距離と照明を確認")
                    .replace("撮影準備はスマホ", shoot)
                    .replace("読取完了はスマホ", "ダブルタップで終了")
                    .replace("次ページ / 完了はスマホ", "前スワイプで次・ダブルタップで終了")
                    .replace("完了はスマホ", "ダブルタップで終了")
                    .replace("登録はスマホのボタン", "無操作で保存")
                    .replace("確認はスマホ", "前スワイプで撮り直し")
                    .replace("撮り直しはスマホ", "前スワイプで撮り直し")
                    .replace("再撮影はスマホ", "前スワイプで撮り直し")
                    .replace("シャッターはスマホ", shoot)
                    .replace("解説操作はスマホ", "前後スワイプで移動")
                    .replace("操作はスマホ", "前後スワイプで移動")
                    .replace("スマホ画面を確認", WAY_OUT)
                    .replace("Hi Rokid認可・再接続", WAY_OUT)
                    .replace("Hi Rokidを再接続してください", WAY_OUT)
                    .replace("Hi Rokidを再接続", WAY_OUT)
                    .replace("Hi Rokidを認可", shoot));
        }
        return adapted;
    }
}
