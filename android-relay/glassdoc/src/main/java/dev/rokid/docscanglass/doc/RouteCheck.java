package dev.rokid.docscanglass.doc;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Map;

import dev.rokid.docscanrelay.DocScanApi;

/**
 * The chooser's word on whether answers can come: what the phone's server found when it last tried its answer
 * routes (the Codex CLI, then Work, then Chat). At the venue nobody looks at the phone, and until this line a
 * signed-out CLI, a spent allowance or a changed web page was found only after a booklet had been photographed and
 * no answer came.
 *
 * <p>Only the fixed words here and one number are ever shown. A route's code, a provider's words, an address, a key
 * or an error's text never are; a route this app has no short name for is counted and not named.</p>
 */
final class RouteCheck {
    static final String ASKING = "経路 …";
    static final String UNREACHED = "経路 ? サーバーに届きません";
    private static final String NONE = "経路 × 答えは届きません";
    /** A kept result older than this, by the glasses' clock, is checked again. */
    private static final long FRESH_SECONDS = 30 * 60;
    private static final Map<String, String> SHORT =
            Map.of("codex-cli", "Codex", "chatgpt-work", "Work", "chatgpt-web", "Chat");

    private RouteCheck() { }

    /**
     * One reading of what the server keeps and, when that is missing or old, one check made now: two bounded
     * requests at most (DocScanApi), never repeated. Blocks; not for the UI thread.
     */
    static String ask(DocScanApi api, long nowSeconds) {
        try {
            JSONObject kept = api.keptRouteCheck();
            return line(fresh(kept, nowSeconds) ? kept : api.routeCheck());
        } catch (Exception unreached) { // its text may hold an address or the server's words
            return UNREACHED;
        }
    }

    /** A time in the future counts as old: the two clocks disagree, so the result's age is not known. */
    static boolean fresh(JSONObject check, long nowSeconds) {
        long checked = check == null ? 0 : check.optLong("checked_at");
        return checked > 0 && checked <= nowSeconds && nowSeconds - checked <= FRESH_SECONDS;
    }

    static String line(JSONObject check) {
        JSONArray routes = check == null ? null : check.optJSONArray("routes");
        if (routes == null) return UNREACHED;
        int passed = 0;
        StringBuilder failed = new StringBuilder();
        String used = "";
        for (int index = 0; index < routes.length(); index++) {
            JSONObject route = routes.optJSONObject(index);
            if (route == null) return UNREACHED;
            String name = SHORT.get(route.optString("name"));
            if (route.optBoolean("ok")) passed++;
            else if (name != null) failed.append(failed.length() == 0 ? "" : " ").append(name).append('×');
            JSONObject usage = route.optJSONObject("usage");
            double percent = usage == null ? Double.NaN : usage.optDouble("used_percent");
            if (percent >= 0 && percent < 1000) used = " 使用" + (long) percent + "%";
        }
        if (passed == 0) return NONE;
        if (passed == routes.length()) return "経路 ○" + used;
        return "経路 △" + (failed.length() == 0 ? "" : " (" + failed + ")") + used;
    }
}
