package dev.rokid.docscanglass.doc;

import java.util.ArrayList;
import java.util.List;

/** Operator instructions for the local glasses surface. */
final class GlassesHudText {
    private GlassesHudText() {
    }

    static List<String> adapt(List<String> lines) {
        List<String> adapted = new ArrayList<>(lines.size());
        for (String line : lines) {
            adapted.add((line == null ? "" : line)
                    .replace("撮影準備はスマホ", "タップで撮影準備")
                    .replace("読取完了はスマホ", "前スワイプで完了")
                    .replace("次ページ / 完了はスマホ", "タップで次・前スワイプで完了")
                    .replace("完了はスマホ", "前スワイプで完了")
                    .replace("登録はスマホのボタン", "タップで登録")
                    .replace("確認はスマホ", "後スワイプで撮り直し")
                    .replace("撮り直しはスマホ", "後スワイプで撮り直し")
                    .replace("再撮影はスマホ", "後スワイプで撮り直し")
                    .replace("シャッターはスマホ", "タップで撮影")
                    .replace("解説操作はスマホ", "前後スワイプで移動")
                    .replace("操作はスマホ", "前後スワイプで移動")
                    .replace("スマホ画面を確認", "設定・接続を確認")
                    .replace("Hi Rokid認可・再接続", "撮影終了後にアプリ再起動")
                    .replace("Hi Rokidを再接続してください", "撮影終了後にアプリを再起動してください")
                    .replace("Hi Rokidを再接続", "撮影終了後にアプリ再起動")
                    .replace("Hi Rokidを認可", "タップで撮影準備"));
        }
        return adapted;
    }
}
