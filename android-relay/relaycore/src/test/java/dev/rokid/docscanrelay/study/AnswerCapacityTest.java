package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.InputStream;
import java.io.SequenceInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.List;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(manifest = Config.NONE, sdk = 28)
public class AnswerCapacityTest {
    @Rule public TemporaryFolder temp = new TemporaryFolder();

    @Test public void twoLargeWorkStagesRemainReadableAndDurableAfterMathematicalExpansion() throws Exception {
        // Each stage starts below Work's 8 MiB source-result bound. A long
        // subscript group can convert its ASCII digits to three-byte glyphs.
        int length = 7_900_000;
        String header = "{\"schema_version\":1,\"session_id\":\"s\",\"input_digest\":\""
                + "a".repeat(64) + "\",\"revision\":2,\"analysis_stage\":\"complete\","
                + "\"available_stage\":\"complete\",\"items\":[";
        InputStream source = new SequenceInputStream(Collections.enumeration(List.of(
                text(header + itemPrefix("q1")), glyphs(length), text("\"}," + itemPrefix("q2")),
                glyphs(length), text("\"}]}"))));
        AnswerBundle bundle = AnswerBundle.fromStream(source);
        assertEquals(2, bundle.items.size());
        for (AnswerItem item : bundle.items) {
            assertEquals(length, item.answer.length());
            assertEquals('₄', item.answer.charAt(length - 1));
        }
        AnswerReader reader = new AnswerReader(bundle, 80, 3, String::length, true);
        reader.restore("q2", length - 16);
        assertEquals("q2", reader.current().questionId);
        assertTrue(reader.page().lines.get(reader.page().lines.size() - 1).endsWith("₄"));
        File directory = temp.newFolder();
        AnswerStore store = new AnswerStore(directory);
        store.start(bundle);
        store.save(bundle, "q2", length - 16, true);
        AnswerStore.Saved saved = new AnswerStore(directory).load();
        assertTrue(saved.closed);
        assertEquals(length - 16, saved.offset);
        assertEquals(bundle.items.get(0).answer, saved.bundle.items.get(0).answer);
        assertEquals(bundle.items.get(1).answer, saved.bundle.items.get(1).answer);
    }

    private static String itemPrefix(String id) {
        return "{\"group_id\":\"g\",\"group_label\":\"全問\",\"question_id\":\"" + id
                + "\",\"question_label\":\"1\",\"status\":\"ready\",\"issue\":\"\",\"answer\":\"";
    }

    private static InputStream text(String value) {
        return new ByteArrayInputStream(value.getBytes(StandardCharsets.UTF_8));
    }

    private static InputStream glyphs(int count) {
        return new InputStream() {
            private final byte[] glyph = "₄".getBytes(StandardCharsets.UTF_8);
            private int position;
            private final int length = count * glyph.length;

            @Override public int read() {
                return position == length ? -1 : glyph[position++ % glyph.length] & 0xff;
            }

            @Override public int read(byte[] buffer, int offset, int size) {
                if (position == length) return -1;
                int copied = Math.min(size, length - position);
                for (int i = 0; i < copied; i++) buffer[offset + i] = glyph[position++ % glyph.length];
                return copied;
            }
        };
    }
}
