package dev.rokid.docscanglass.probe;

import android.os.SystemClock;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.SocketException;
import java.net.URL;
import java.util.Collections;

/**
 * P3: do the glasses reach the FastAPI server over their own Wi-Fi?
 *
 * <p>The repository has always routed the server through the phone. Whether
 * that is necessary or merely historical is the question this settles, because
 * a glasses-direct answer removes the CUSTOMVIEW overlay, the Hi Rokid AIDL
 * binding, and the phone-must-stay-awake constraint from the design.
 *
 * <p>Reports the status line and round trip only. The response body is never
 * read into the report or the log.
 */
final class NetworkProbe {

    private static final int CONNECT_TIMEOUT_MILLIS = 5_000;
    private static final int READ_TIMEOUT_MILLIS = 5_000;

    private NetworkProbe() {
    }

    /**
     * Local IPv4 addresses, which say whether the glasses joined a network at
     * all. Interface enumeration needs no permission; the SSID would need
     * location access and is not worth asking for to answer this.
     */
    static String describeLink() {
        StringBuilder found = new StringBuilder();
        try {
            for (NetworkInterface each
                    : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (each.isLoopback() || !each.isUp()) {
                    continue;
                }
                for (InetAddress address : Collections.list(each.getInetAddresses())) {
                    if (!(address instanceof Inet4Address)) {
                        continue;
                    }
                    if (found.length() > 0) {
                        found.append(' ');
                    }
                    found.append(each.getName()).append('=').append(address.getHostAddress());
                }
            }
        } catch (SocketException error) {
            return "interfaces unreadable: " + error.getClass().getSimpleName();
        }
        return found.length() == 0 ? "no IPv4 address" : found.toString();
    }

    /** One GET against {@code baseUrl + path}. Never returns or logs the body. */
    static String get(String baseUrl, String path) {
        String target = baseUrl.endsWith("/")
                ? baseUrl.substring(0, baseUrl.length() - 1) + path
                : baseUrl + path;
        long startedAt = SystemClock.elapsedRealtime();
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(target).openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(CONNECT_TIMEOUT_MILLIS);
            connection.setReadTimeout(READ_TIMEOUT_MILLIS);
            connection.setUseCaches(false);
            int status = connection.getResponseCode();
            long elapsed = SystemClock.elapsedRealtime() - startedAt;
            return path + " " + status + " in " + elapsed + "ms";
        } catch (IOException | RuntimeException error) {
            long elapsed = SystemClock.elapsedRealtime() - startedAt;
            return path + " " + error.getClass().getSimpleName() + " after " + elapsed + "ms";
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }
}
