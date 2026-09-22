package dev.rokid.docscanglass.doc;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.io.*;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.Properties;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import okhttp3.HttpUrl;

/** One authenticated server/key pair; the encryption key stays in Android Keystore. */
final class ConnectionSettings {
    private static final int MAGIC = 0x47444331;
    private static final String ALIAS = "docscan-connection-v1";
    private final File file;
    private final SecretKey suppliedKey;

    ConnectionSettings(File file) { this(file, null); }

    ConnectionSettings(File file, SecretKey key) {
        this.file = file;
        suppliedKey = key;
    }

    static final class Saved {
        final String server;
        final String key;
        Saved(String server, String key) { this.server = server; this.key = key; }
    }

    /** Initial setup is delivered through run-as stdin, so credentials never appear in an adb command. */
    synchronized Saved provisioning() throws IOException {
        File setup = new File(file.getParentFile(), "setup.properties");
        if (!setup.exists()) return null;
        if (setup.length() > 16384) throw new IOException("初回設定が大きすぎます");
        Properties values = new Properties();
        try (InputStream input = new FileInputStream(setup)) { values.load(input); }
        if (values.size() != 2 || !values.containsKey("server") || !values.containsKey("key")) {
            throw new IOException("初回設定の形式を確認してください");
        }
        return new Saved(normalizeServer(values.getProperty("server")), values.getProperty("key").trim());
    }

    static String normalizeServer(String value) {
        String server = value == null ? "" : value.trim().replaceAll("/+$", "");
        HttpUrl url = HttpUrl.parse(server);
        if (server.length() > 4096 || url == null || !url.username().isEmpty()
                || !url.password().isEmpty() || url.query() != null || url.fragment() != null) {
            throw new IllegalArgumentException("サーバURLの形式を確認してください");
        }
        return server;
    }

    synchronized void save(String server, String apiKey) throws IOException {
        Saved setup = provisioning();
        server = normalizeServer(server);
        String value = apiKey == null ? "" : apiKey.trim();
        if (value.length() > 8192 || value.chars().anyMatch(c -> c < 32 || c > 126)) {
            throw new IllegalArgumentException("認証鍵の形式を確認してください");
        }
        byte[] encrypted;
        byte[] iv;
        try {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (DataOutputStream data = new DataOutputStream(bytes)) {
                data.writeUTF(server);
                data.writeUTF(value);
            }
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key(true));
            iv = cipher.getIV();
            encrypted = cipher.doFinal(bytes.toByteArray());
        } catch (GeneralSecurityException error) {
            throw new IOException("接続設定を暗号化できません");
        }
        Files.createDirectories(file.getParentFile().toPath());
        File temporary = new File(file.getParentFile(), file.getName() + ".tmp");
        try (FileOutputStream stream = new FileOutputStream(temporary);
             DataOutputStream data = new DataOutputStream(stream)) {
            data.writeInt(MAGIC);
            data.writeInt(iv.length);
            data.write(iv);
            data.write(encrypted);
            data.flush();
            stream.getFD().sync();
        }
        try {
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException error) {
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING);
        }
        if (setup != null && server.equals(setup.server) && value.equals(setup.key)) {
            Files.delete(new File(file.getParentFile(), "setup.properties").toPath());
        }
    }

    synchronized Saved load() throws IOException {
        if (!file.exists()) return null;
        if (file.length() < 36 || file.length() > 65536) throw new IOException("接続設定を読み出せません");
        try (DataInputStream data = new DataInputStream(new FileInputStream(file))) {
            if (data.readInt() != MAGIC || data.readInt() != 12) throw new IOException("接続設定の形式が不正です");
            byte[] iv = new byte[12];
            data.readFully(iv);
            byte[] encrypted = new byte[(int) file.length() - 20];
            data.readFully(encrypted);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, iv));
            try (DataInputStream plain = new DataInputStream(new ByteArrayInputStream(cipher.doFinal(encrypted)))) {
                Saved saved = new Saved(plain.readUTF(), plain.readUTF());
                if (plain.read() != -1) throw new IOException("接続設定の形式が不正です");
                return saved;
            }
        } catch (GeneralSecurityException error) {
            // Never replace a missing Keystore key or discard the encrypted original while loading.
            throw new IOException("接続設定を復号できません。初回設定を確認してください");
        }
    }

    private SecretKey key(boolean create) throws GeneralSecurityException, IOException {
        if (suppliedKey != null) return suppliedKey;
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        SecretKey key = (SecretKey) store.getKey(ALIAS, null);
        if (key != null) return key;
        if (!create) throw new GeneralSecurityException("Missing encryption key");
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }
}
