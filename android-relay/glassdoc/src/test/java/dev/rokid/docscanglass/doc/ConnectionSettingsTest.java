package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class ConnectionSettingsTest {
    @Rule public TemporaryFolder folder = new TemporaryFolder();

    @Test public void restartRestoresAuthenticatedSettingsAndCorruptionKeepsOriginalFile() throws Exception {
        File file = new File(folder.getRoot(), "connection.bin");
        SecretKey key = KeyGenerator.getInstance("AES").generateKey();
        ConnectionSettings settings = new ConnectionSettings(file, key);
        assertNull(settings.load());
        settings.save("http://192.168.1.1:8000/", "test-only-credential");
        byte[] first = Files.readAllBytes(file.toPath());
        assertFalse(new String(first, StandardCharsets.UTF_8).contains("test-only-credential"));
        ConnectionSettings.Saved restored = new ConnectionSettings(file, key).load();
        assertEquals("http://192.168.1.1:8000", restored.server);
        assertEquals("test-only-credential", restored.key);
        settings.save(restored.server, restored.key);
        assertFalse(java.util.Arrays.equals(first, Files.readAllBytes(file.toPath())));

        assertThrows(IllegalArgumentException.class,
                () -> settings.save("http://user:password@example.test", "replacement"));
        assertEquals(restored.key, settings.load().key);
        // An interrupted write must not replace the last complete encrypted file.
        Files.write(new File(folder.getRoot(), "connection.bin.tmp").toPath(), new byte[] {1});
        assertEquals(restored.key, new ConnectionSettings(file, key).load().key);
        byte[] damaged = Files.readAllBytes(file.toPath());
        damaged[damaged.length - 1] ^= 1;
        Files.write(file.toPath(), damaged);
        assertThrows(IOException.class, settings::load);
        assertArrayEquals(damaged, Files.readAllBytes(file.toPath()));
    }

    @Test public void acceptedPrivateSetupIsConsumedOnlyAfterTheMatchingCredentialIsSaved() throws Exception {
        File file = new File(folder.getRoot(), "connection.bin");
        File setup = new File(folder.getRoot(), "setup.properties");
        Files.write(setup.toPath(), "server=http://phone:8000\nkey=test-only-credential\n".getBytes(StandardCharsets.UTF_8));
        ConnectionSettings settings = new ConnectionSettings(file, KeyGenerator.getInstance("AES").generateKey());
        ConnectionSettings.Saved provisioned = settings.provisioning();
        settings.save("http://previous:8000", "previous-test-key");
        assertTrue(setup.exists());
        settings.save(provisioned.server, provisioned.key);
        assertFalse(setup.exists());
        assertEquals(provisioned.key, settings.load().key);
    }
}
