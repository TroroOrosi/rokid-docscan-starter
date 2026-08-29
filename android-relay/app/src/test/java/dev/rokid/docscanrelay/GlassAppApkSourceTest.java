package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class GlassAppApkSourceTest {

    @Rule
    public final TemporaryFolder folder = new TemporaryFolder();

    @Test
    public void acceptsAFileThatBeginsLikeAZip() throws IOException {
        write(new byte[]{0x50, 0x4B, 0x03, 0x04, 0x14, 0x00});

        GlassAppApkSource source = GlassAppApkSource.resolve(folder.getRoot());

        assertTrue(source.usable());
        assertEquals(GlassAppApkSource.FILE_NAME, source.file().getName());
        assertEquals("", source.problem());
        assertTrue(source.summary().endsWith("bytes=6"));
    }

    @Test
    public void namesThePathTheOperatorMustPushToWhenNothingIsThere() {
        GlassAppApkSource source = GlassAppApkSource.resolve(folder.getRoot());

        assertFalse(source.usable());
        assertTrue(source.problem().startsWith("APKがありません: "));
        assertTrue(source.problem().endsWith(GlassAppApkSource.FILE_NAME));
    }

    @Test
    public void rejectsAnEmptyFile() throws IOException {
        write(new byte[0]);

        GlassAppApkSource source = GlassAppApkSource.resolve(folder.getRoot());

        assertFalse(source.usable());
        assertTrue(source.problem().startsWith("APKが空です: "));
    }

    @Test
    public void rejectsAFileThatIsNotAnApkSoAPartialPushIsNotReadAsARefusal() throws IOException {
        write("not an apk".getBytes("UTF-8"));

        GlassAppApkSource source = GlassAppApkSource.resolve(folder.getRoot());

        assertFalse(source.usable());
        assertTrue(source.problem().startsWith("APKではありません"));
    }

    @Test
    public void rejectsAFileShorterThanTheZipHeader() throws IOException {
        write(new byte[]{0x50, 0x4B});

        GlassAppApkSource source = GlassAppApkSource.resolve(folder.getRoot());

        assertFalse(source.usable());
        assertTrue(source.problem().startsWith("APKではありません"));
    }

    @Test
    public void rejectsADirectoryStandingWhereTheApkShouldBe() {
        assertTrue(new File(folder.getRoot(), GlassAppApkSource.FILE_NAME).mkdir());

        GlassAppApkSource source = GlassAppApkSource.resolve(folder.getRoot());

        assertFalse(source.usable());
        assertTrue(source.problem().startsWith("APKの場所がファイルではありません: "));
    }

    @Test
    public void reportsAMissingExternalFilesDirectoryRatherThanCrashing() {
        GlassAppApkSource source = GlassAppApkSource.resolve(null);

        assertFalse(source.usable());
        assertEquals("外部ファイル領域が利用できません", source.problem());
        assertEquals("glass-app apk unusable: 外部ファイル領域が利用できません", source.summary());
    }

    private void write(byte[] bytes) throws IOException {
        File target = new File(folder.getRoot(), GlassAppApkSource.FILE_NAME);
        try (OutputStream stream = new FileOutputStream(target)) {
            stream.write(bytes);
        }
    }
}
