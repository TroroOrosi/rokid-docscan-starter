package dev.rokid.docscanrelay;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;

/**
 * Locates and vets the APK the relay uploads to the glasses.
 *
 * <p>The file is pushed with {@code adb push} into the relay's own external
 * files directory, which the shell user can write and the app can read without
 * holding any storage permission. Bundling it as an asset instead would put a
 * throwaway probe inside every relay build.
 *
 * <p>The vetting is the point. {@code uploadAndInstallApk} reports one boolean,
 * so a truncated push, a wrong path, or a text file left behind by a failed
 * transfer would all surface as {@code false} — indistinguishable from the
 * firmware refusing the route this probe exists to test. Everything checkable
 * before the call is checked here instead.
 */
final class GlassAppApkSource {

    static final String FILE_NAME = "glassapp.apk";

    /** Local file header of every zip, and therefore of every APK. */
    private static final byte[] ZIP_MAGIC = {0x50, 0x4B, 0x03, 0x04};

    private final File file;
    private final String problem;

    private GlassAppApkSource(File file, String problem) {
        this.file = file;
        this.problem = problem;
    }

    static GlassAppApkSource resolve(File directory) {
        if (directory == null) {
            return new GlassAppApkSource(
                    null, "外部ファイル領域が利用できません");
        }
        File candidate = new File(directory, FILE_NAME);
        if (!candidate.exists()) {
            return new GlassAppApkSource(
                    null, "APKがありません: " + candidate.getAbsolutePath());
        }
        if (!candidate.isFile()) {
            return new GlassAppApkSource(
                    null, "APKの場所がファイルではありません: " + candidate.getAbsolutePath());
        }
        if (candidate.length() == 0) {
            return new GlassAppApkSource(
                    null, "APKが空です: " + candidate.getAbsolutePath());
        }
        if (!startsWithZipMagic(candidate)) {
            return new GlassAppApkSource(
                    null,
                    "APKではありません（転送が途中で切れた可能性）: "
                            + candidate.getAbsolutePath());
        }
        return new GlassAppApkSource(candidate, "");
    }

    boolean usable() {
        return file != null;
    }

    File file() {
        return file;
    }

    String problem() {
        return problem;
    }

    String summary() {
        if (!usable()) {
            return "glass-app apk unusable: " + problem;
        }
        return "glass-app apk " + file.getAbsolutePath() + " bytes=" + file.length();
    }

    private static boolean startsWithZipMagic(File candidate) {
        byte[] head = new byte[ZIP_MAGIC.length];
        try (InputStream stream = new FileInputStream(candidate)) {
            int read = 0;
            while (read < head.length) {
                int chunk = stream.read(head, read, head.length - read);
                if (chunk < 0) {
                    return false;
                }
                read += chunk;
            }
        } catch (IOException error) {
            return false;
        }
        for (int index = 0; index < ZIP_MAGIC.length; index++) {
            if (head[index] != ZIP_MAGIC[index]) {
                return false;
            }
        }
        return true;
    }
}
