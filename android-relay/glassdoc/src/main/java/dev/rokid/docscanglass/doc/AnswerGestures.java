package dev.rokid.docscanglass.doc;

import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanrelay.study.AnswerReader;

/**
 * The four gestures the firmware delivers, mapped onto the reader's own verbs.
 *
 * <p>Pure on purpose: the Activity owns the display and the persistence, this
 * owns the decision, and the decision is the part worth testing.</p>
 */
final class AnswerGestures {
    private AnswerGestures() {
    }

    /** @return true while the reader keeps the screen, false once it is left. */
    static boolean apply(AnswerReader reader, GlassesInputAction action) {
        switch (action) {
            case SWIPE_FORWARD:
                reader.forward();
                return true;
            case SWIPE_BACK:
                reader.backward();
                return true;
            case SHORT_TAP:
                reader.tap();
                return true;
            case BACK:
                // AnswerReader#back() returns true only when the host should
                // persist CLOSED and leave answer reading -- the opposite of
                // this method's own contract. Negate to keep "true means the
                // reader keeps the screen" true for every case, not just three
                // of four.
                return !reader.back();
            default:
                return true;
        }
    }
}
