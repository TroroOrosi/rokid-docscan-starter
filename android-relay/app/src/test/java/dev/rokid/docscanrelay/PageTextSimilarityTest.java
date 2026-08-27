package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class PageTextSimilarityTest {
    private static final String PAGE_ONE =
            "問1 次の文章を読んで後の問いに答えなさい。江戸時代の交通路は幕府によって整備され、"
                    + "五街道と呼ばれる主要な道が江戸を起点として全国へ延びていた。";
    private static final String PAGE_TWO =
            "問2 右の地図を見て答えなさい。明治政府は殖産興業の方針のもと官営工場を各地に設け、"
                    + "民間へ払い下げることで近代産業の基礎を築いた。";

    @Test
    public void twoShotsOfOnePageReadAsTheSamePage() {
        // A few glyphs differ between shots; the sheet has not been turned.
        String secondShot = PAGE_ONE
                .replace("整備され", "整偏され")
                .replace("全国へ", "全圄へ");

        assertTrue(PageTextSimilarity.isSamePage(PAGE_ONE, secondShot));
    }

    @Test
    public void theNextPageIsNotTheSamePage() {
        assertFalse(PageTextSimilarity.isSamePage(PAGE_ONE, PAGE_TWO));
    }

    @Test
    public void identicalTextIsTheSamePage() {
        assertTrue(PageTextSimilarity.isSamePage(PAGE_ONE, PAGE_ONE));
    }

    @Test
    public void whitespaceAndLineBreaksDoNotMakeItADifferentPage() {
        String reflowed = PAGE_ONE.replace("。", "。\n").replace(" ", "");

        assertTrue(PageTextSimilarity.isSamePage(PAGE_ONE, reflowed));
    }

    @Test
    public void textTooShortToJudgeIsNotTreatedAsADuplicate() {
        // Failing toward "different page" keeps a badly-read page registrable.
        assertFalse(PageTextSimilarity.isSamePage("問1", "問1"));
        assertFalse(PageTextSimilarity.isSamePage(PAGE_ONE, ""));
        assertFalse(PageTextSimilarity.isSamePage(null, PAGE_ONE));
        assertFalse(PageTextSimilarity.isSamePage(PAGE_ONE, null));
    }

    @Test
    public void aHalfTurnedPageIsNotSuppressed() {
        // Only the tail of page one is still visible next to page two's head.
        String halfTurned = PAGE_ONE.substring(PAGE_ONE.length() - 20)
                + PAGE_TWO.substring(0, 40);

        assertFalse(PageTextSimilarity.isSamePage(PAGE_ONE, halfTurned));
    }
}
