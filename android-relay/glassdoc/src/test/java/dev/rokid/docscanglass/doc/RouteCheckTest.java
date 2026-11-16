package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.concurrent.TimeUnit;

import dev.rokid.docscanrelay.ClientIdentity;
import dev.rokid.docscanrelay.DocScanApi;
import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okhttp3.mockwebserver.SocketPolicy;

/**
 * The chooser's line on the answer routes: which fixed words stand for what the phone's server found, and which of
 * the two requests are made. The replies here have the shape of {@code run_route_check} in the server's main.py.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class RouteCheckTest {
    private static final long NOW = 1_795_000_000L;
    private static final String USED = ",\"usage\":{\"used_percent\":3.9,\"window_minutes\":10080,\"resets_at\":1795429113}";

    private MockWebServer server;
    private DocScanApi api;

    @Before public void setUp() throws Exception {
        server = new MockWebServer();
        server.start();
        api = new DocScanApi(server.url("/").toString(), "route-test-key", new ClientIdentity("test-glasses", "route-test/1", "none"));
    }

    @After public void tearDown() throws Exception {
        server.shutdown();
    }

    private static String route(String name, boolean ok, String more) {
        return "{\"name\":\"" + name + "\",\"ok\":" + ok + ",\"code\":\"" + (ok ? "ok" : "rate_limited")
                + "\",\"real\":" + "codex-cli".equals(name) + ",\"seconds\":5.2" + more + "}";
    }

    private static String checked(long at, String... routes) {
        boolean any = false;
        for (String route : routes) any |= route.contains("\"ok\":true");
        return "{\"checked_at\":" + at + ",\"ok\":" + any + ",\"routes\":[" + String.join(",", routes) + "]}";
    }

    private static String lineOf(String... routes) throws Exception {
        return RouteCheck.line(new JSONObject(checked(NOW - 60, routes)));
    }

    // --- the words ------------------------------------------------------------------------------------------------

    @Test public void every_route_passed_is_a_circle() throws Exception {
        assertEquals("経路 ○", lineOf(route("codex-cli", true, ""), route("chatgpt-work", true, ""), route("chatgpt-web", true, "")));
    }

    @Test public void a_known_usage_follows_as_the_whole_part_of_its_percent() throws Exception {
        assertEquals("3.9 is shown as 3", "経路 ○ 使用3%",
                lineOf(route("codex-cli", true, USED), route("chatgpt-work", true, ""), route("chatgpt-web", true, "")));
    }

    @Test public void a_route_that_failed_beside_one_that_passed_is_a_triangle_with_its_short_name() throws Exception {
        assertEquals("経路 △ (Codex×)",
                lineOf(route("codex-cli", false, ""), route("chatgpt-work", true, ""), route("chatgpt-web", true, "")));
        assertEquals("every failed route is named, and the usage follows when it is known", "経路 △ (Work× Chat×) 使用3%",
                lineOf(route("codex-cli", true, USED), route("chatgpt-work", false, ""), route("chatgpt-web", false, "")));
    }

    @Test public void no_route_passed_says_that_answers_will_not_come() throws Exception {
        assertEquals("経路 × 答えは届きません",
                lineOf(route("codex-cli", false, ""), route("chatgpt-work", false, ""), route("chatgpt-web", false, "")));
        assertEquals("a server with no route at all cannot answer either", "経路 × 答えは届きません", lineOf());
    }

    @Test public void a_reply_that_cannot_be_read_says_the_server_is_not_reached() throws Exception {
        assertEquals("経路 ? サーバーに届きません", RouteCheck.line(null));
        assertEquals("経路 ? サーバーに届きません", RouteCheck.line(new JSONObject("{\"detail\":\"Not Found\"}")));
        assertEquals("経路 ? サーバーに届きません", RouteCheck.line(new JSONObject("{\"checked_at\":1,\"routes\":[\"codex-cli\"]}")));
    }

    @Test public void nothing_of_a_reply_is_shown_but_the_fixed_words_and_the_number() throws Exception {
        String line = RouteCheck.line(new JSONObject("{\"checked_at\":" + NOW + ",\"ok\":true,\"routes\":["
                + "{\"name\":\"http://10.0.0.7:8000/secret-key\",\"ok\":false,\"code\":\"You've hit your usage limit\"},"
                + "{\"name\":\"chatgpt-web\",\"ok\":true,\"code\":\"ok\",\"usage\":{\"used_percent\":\"words of the provider\"}}]}"));
        assertEquals("a route this app has no name for is counted and not named", "経路 △", line);
    }

    // --- which requests are made ----------------------------------------------------------------------------------

    @Test public void a_result_is_fresh_for_thirty_minutes_and_one_from_the_future_is_old() throws Exception {
        assertTrue(RouteCheck.fresh(new JSONObject(checked(NOW - 30 * 60)), NOW));
        assertFalse(RouteCheck.fresh(new JSONObject(checked(NOW - 30 * 60 - 1)), NOW));
        assertTrue(RouteCheck.fresh(new JSONObject(checked(NOW)), NOW));
        assertFalse("the clocks disagree: its age is not known", RouteCheck.fresh(new JSONObject(checked(NOW + 1)), NOW));
        assertFalse(RouteCheck.fresh(null, NOW));
        assertFalse(RouteCheck.fresh(new JSONObject("{\"routes\":[]}"), NOW));
    }

    @Test public void a_fresh_kept_result_is_shown_from_one_reading_of_the_settings() throws Exception {
        serve("{\"hud\":{\"max_lines\":3},\"route_check\":" + checked(NOW - 60, route("codex-cli", true, USED)) + "}", "{}");

        assertEquals("経路 ○ 使用3%", RouteCheck.ask(api, NOW));

        assertEquals("nothing is checked again", 1, server.getRequestCount());
        RecordedRequest read = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(read);
        assertEquals("GET", read.getMethod());
        assertEquals("/v1/settings", read.getPath());
        assertEquals("Bearer route-test-key", read.getHeader("Authorization"));
    }

    @Test public void a_kept_result_over_thirty_minutes_old_makes_exactly_one_check_now() throws Exception {
        serve("{\"route_check\":" + checked(NOW - 31 * 60, route("codex-cli", true, USED)) + "}",
                checked(NOW, route("codex-cli", false, ""), route("chatgpt-web", true, "")));

        assertEquals("what the check made now found, not the old result", "経路 △ (Codex×)", RouteCheck.ask(api, NOW));

        assertEquals(2, server.getRequestCount());
        assertEquals("/v1/settings", server.takeRequest(1, TimeUnit.SECONDS).getPath());
        RecordedRequest check = server.takeRequest(1, TimeUnit.SECONDS);
        assertEquals("POST", check.getMethod());
        assertEquals("/v1/route-check", check.getPath());
        assertEquals("Bearer route-test-key", check.getHeader("Authorization"));
    }

    @Test public void a_server_that_keeps_no_result_makes_exactly_one_check_now() throws Exception {
        serve("{\"route_check\":null}", checked(NOW, route("codex-cli", true, "")));

        assertEquals("経路 ○", RouteCheck.ask(api, NOW));

        assertEquals(2, server.getRequestCount());
        assertEquals("GET", server.takeRequest(1, TimeUnit.SECONDS).getMethod());
        assertEquals("POST", server.takeRequest(1, TimeUnit.SECONDS).getMethod());
    }

    @Test public void a_check_now_that_is_itself_old_by_the_glasses_clock_is_shown_and_not_asked_for_again() throws Exception {
        serve("{\"route_check\":null}", checked(NOW + 7200, route("codex-cli", true, "")));

        assertEquals("経路 ○", RouteCheck.ask(api, NOW));

        assertEquals("one reading and one check, whatever the two clocks say", 2, server.getRequestCount());
    }

    @Test public void a_server_that_answers_an_error_is_not_asked_again_and_none_of_its_words_are_shown() throws Exception {
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                return new MockResponse().setResponseCode(500).setBody("{\"detail\":\"Traceback: secret-key at 10.0.0.7\"}");
            }
        });

        assertEquals("経路 ? サーバーに届きません", RouteCheck.ask(api, NOW));

        assertEquals(1, server.getRequestCount());
    }

    @Test public void a_check_now_that_fails_is_not_repeated() throws Exception {
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                return "/v1/settings".equals(request.getPath()) ? new MockResponse().setBody("{}")
                        : new MockResponse().setResponseCode(401).setBody("{\"detail\":\"Unauthorized\"}");
            }
        });

        assertEquals("経路 ? サーバーに届きません", RouteCheck.ask(api, NOW));

        assertEquals(2, server.getRequestCount());
    }

    @Test public void a_server_that_is_not_there_is_not_reached() throws Exception {
        server.shutdown();

        assertEquals("経路 ? サーバーに届きません", RouteCheck.ask(api, NOW));
    }

    /** The app's ordinary requests wait minutes for a reply; the chooser's reading of the settings gives up in seconds. */
    @Test public void a_server_that_never_answers_the_reading_is_given_up_within_seconds() throws Exception {
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                return new MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE);
            }
        });
        long started = System.nanoTime();

        assertEquals("経路 ? サーバーに届きません", RouteCheck.ask(api, NOW));

        long seconds = TimeUnit.NANOSECONDS.toSeconds(System.nanoTime() - started);
        assertTrue("gave up after " + seconds + " s", seconds >= 3 && seconds < 15);
        assertEquals("and does not go on to the check", 1, server.getRequestCount());
    }

    private void serve(String settings, String checkedNow) {
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                if ("GET".equals(request.getMethod()) && "/v1/settings".equals(request.getPath())) {
                    return new MockResponse().setBody(settings);
                }
                if ("POST".equals(request.getMethod()) && "/v1/route-check".equals(request.getPath())) {
                    return new MockResponse().setBody(checkedNow);
                }
                return new MockResponse().setResponseCode(404).setBody("{\"detail\":\"Not Found\"}");
            }
        });
    }
}
