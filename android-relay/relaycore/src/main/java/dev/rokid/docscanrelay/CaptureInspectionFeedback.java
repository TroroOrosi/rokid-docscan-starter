package dev.rokid.docscanrelay;

// bounded, capture-bound diagnostic reads; no image ACK or capture authority.
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.LongSupplier;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Reads an opt-in diagnosis for one latest original. No result can authorize a capture. */
public final class CaptureInspectionFeedback implements AutoCloseable {
    public static final int MAX_RESPONSE_BYTES = 512 * 1024;
    public enum Outcome { ISSUE, UNKNOWN, NO_ISSUE_OBSERVED }

    public interface Query {
        JSONObject execute() throws Exception;
        void cancel();
    }
    public interface Reader { Query open(Binding binding) throws Exception; }

    /** Metadata only; constructed from the strict image receipt and the original run context. */
    public static final class Binding {
        public final String inspectionId, canonicalSha256;
        public final CaptureInspectionOrigin.Context context;
        public final CaptureProvenance source;
        public final long documentId;

        private Binding(String id, String sha, CaptureInspectionOrigin.Context context,
                        CaptureProvenance source, long document) {
            inspectionId = id; canonicalSha256 = sha; this.context = context;
            this.source = source; documentId = document;
        }

        static Binding fromReceipt(CaptureInspectionOrigin.Context context, CaptureProvenance source,
                                   long document, JSONObject receipt) throws JSONException {
            if (context == null || source == null || source.localSessionId == null || source.pageIndex < 0
                    || document <= 0 || document > Integer.MAX_VALUE) return null;
            JSONObject summary = receipt.optJSONObject("capture_inspection");
            // An old/disabled/unbound server must leave the ordinary image receipt unchanged.
            if (summary == null || summary.isNull("inspection_id")) return null;
            String id = hash(summary.opt("inspection_id"));
            require("diagnostic_only".equals(summary.opt("scope")) && summary.opt("status") instanceof String);
            requireFalse(summary, "applicable", "all_pages_or_characters_verified", "auto_registration_allowed");
            require(integer(receipt.opt("document_id"), document)
                    && integer(receipt.opt("page_index"), source.pageIndex));
            source.requireUploadEcho(receipt.optJSONObject("capture_provenance"));
            return new Binding(id, hash(receipt.opt("canonical_image_sha256")), context, source, document);
        }

        /** null means a recognized pending state, not successful inspection. */
        Outcome decode(JSONObject reply) throws JSONException {
            require(inspectionId.equals(reply.opt("inspection_id")) && "diagnostic_only".equals(reply.opt("scope")));
            requireFalse(reply, "can_authorize_capture", "all_pages_or_characters_verified", "auto_registration_allowed");
            require(reply.opt("applicable") instanceof Boolean && reply.opt("status") instanceof String);
            owner(reply.optJSONObject("owner"));
            String status = (String) reply.get("status");
            if (Set.of("queued", "prepared", "processing", "uncertain", "deferred_browser", "deferred_answers", "deferred_send_disabled", "deferred_queue_full").contains(status)) {
                require(Boolean.FALSE.equals(reply.opt("applicable")));
                return null;
            }
            if (!"completed".equals(status) || !Boolean.TRUE.equals(reply.opt("applicable"))) return Outcome.UNKNOWN;
            JSONObject result = reply.optJSONObject("result");
            require(result != null);
            requireFalse(result, "all_pages_or_characters_verified", "auto_registration_allowed");
            JSONArray parts = result.optJSONArray("parts");
            require(parts != null && parts.length() == 1); // This consumer is native-only, never a video/page substitution.
            JSONObject part = parts.optJSONObject(0);
            require(part != null && "bounded_regions_only".equals(part.opt("scope")));
            hash(part.opt("inspection_id")); hash(part.opt("manifest_sha256"));
            owner(part.optJSONObject("owner"));
            requireFalse(part, "independently_verified", "calibrated", "all_pages_or_characters_verified", "auto_registration_allowed");
            JSONArray observations = part.optJSONArray("observations");
            require(observations != null && observations.length() >= 1 && observations.length() <= 6);
            Set<String> images = new HashSet<>();
            boolean issue = false, uncertain = false;
            for (int i = 0; i < observations.length(); i++) {
                JSONObject item = observations.optJSONObject(i);
                require(item != null && item.length() == 4 && item.opt("image_id") instanceof String);
                String image = (String) item.get("image_id");
                require(image.matches("[A-Za-z0-9_-]{1,128}") && images.add(image)
                        && item.opt("image_viewer_used") instanceof Boolean);
                Object observed = item.opt("status");
                require("issue".equals(observed) || "uncertain".equals(observed) || "no_issue_observed".equals(observed));
                JSONArray reasons = item.optJSONArray("reasons");
                require(reasons != null && reasons.length() <= 8
                        && ("no_issue_observed".equals(observed) || reasons.length() > 0));
                for (int j = 0; j < reasons.length(); j++) {
                    Object reason = reasons.opt(j);
                    require(reason instanceof String && !((String) reason).trim().isEmpty() && ((String) reason).length() <= 500);
                }
                if ("no_issue_observed".equals(observed)) require(Boolean.TRUE.equals(item.opt("image_viewer_used")));
                issue |= "issue".equals(observed); uncertain |= "uncertain".equals(observed);
            }
            return issue ? Outcome.ISSUE : uncertain ? Outcome.UNKNOWN : Outcome.NO_ISSUE_OBSERVED;
        }

        private void owner(JSONObject value) throws JSONException {
            require(value != null && value.length() == 10 && "native_capture".equals(value.opt("kind"))
                    && "bounded_diagnostic_v1".equals(value.opt("policy"))
                    && context.deviceId.equals(value.opt("device_id")) && integer(value.opt("generation"), context.generation)
                    && integer(value.opt("document_id"), documentId)
                    && source.localSessionId.equals(value.opt("local_session_id")) && source.captureId.equals(value.opt("capture_id"))
                    && canonicalSha256.equals(value.opt("canonical_image_sha256"))
                    && value.opt("source_ip") instanceof String);
            source.requireUploadEcho(value.optJSONObject("capture_provenance"));
        }
    }

    /** No free-form model output crosses the HUD seam. No-issue has no pass label. */
    public static final class Notice {
        public final Binding binding;
        public final Outcome outcome;
        public Notice(Binding binding, Outcome outcome) { this.binding = binding; this.outcome = outcome; }
        public String text() {
            return outcome == Outcome.NO_ISSUE_OBSERVED ? ""
                    : "P" + (binding.source.pageIndex + 1) + (outcome == Outcome.ISSUE ? " 要確認" : " 未確認");
        }
    }

    private final ScheduledExecutorService worker;
    private final LongSupplier nanos;
    private final int maxReads;
    private final long intervalMillis, budgetNanos;
    private Ticket active;
    private boolean closed;
    private static final class Ticket {
        final Binding binding;
        final Reader reader;
        final BooleanSupplier current;
        final Consumer<Notice> sink;
        final long start;
        int reads;
        Query query;
        ScheduledFuture<?> scheduled;
        Ticket(Binding binding, Reader reader, BooleanSupplier current, Consumer<Notice> sink, long start) {
            this.binding = binding; this.reader = reader; this.current = current; this.sink = sink; this.start = start;
        }
    }

    public CaptureInspectionFeedback() { this(executor(), System::nanoTime, 8, 10_000, 120_000); }
    CaptureInspectionFeedback(ScheduledExecutorService worker, LongSupplier nanos, int maxReads,
                              long intervalMillis, long budgetMillis) {
        if (maxReads < 1 || maxReads > 8 || intervalMillis < 0 || budgetMillis < 1 || budgetMillis > 120_000)
            throw new IllegalArgumentException("invalid diagnostic read budget");
        this.worker = worker; this.nanos = nanos; this.maxReads = maxReads;
        this.intervalMillis = intervalMillis; budgetNanos = TimeUnit.MILLISECONDS.toNanos(budgetMillis);
    }
    private static ScheduledExecutorService executor() {
        ScheduledThreadPoolExecutor executor = new ScheduledThreadPoolExecutor(1);
        executor.setRemoveOnCancelPolicy(true);
        executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
        return executor;
    }

    public synchronized void start(Binding binding, Reader reader, BooleanSupplier current, Consumer<Notice> sink) {
        clear();
        if (closed) return;
        Ticket ticket = new Ticket(binding, reader, current, sink, nanos.getAsLong());
        active = ticket;
        ticket.scheduled = worker.schedule(() -> read(ticket), 0, TimeUnit.MILLISECONDS);
    }

    public synchronized void clear() {
        Ticket old = active; active = null;
        if (old == null) return;
        if (old.scheduled != null) old.scheduled.cancel(false);
        if (old.query != null) old.query.cancel();
    }

    private synchronized boolean current(Ticket ticket) {
        if (closed || active != ticket) return false;
        try { return ticket.current.getAsBoolean(); }
        catch (RuntimeException unavailable) { return false; }
    }

    private void read(Ticket ticket) {
        if (!current(ticket)) return;
        Outcome outcome = Outcome.UNKNOWN;
        try {
            synchronized (this) {
                if (!current(ticket)) return;
                if (ticket.reads >= maxReads || nanos.getAsLong() - ticket.start >= budgetNanos) {
                    ticket.sink.accept(new Notice(ticket.binding, Outcome.UNKNOWN)); return;
                }
                ticket.reads++;
                ticket.query = ticket.reader.open(ticket.binding);
            }
            outcome = ticket.binding.decode(ticket.query.execute());
        } catch (Exception unavailable) {
            // Diagnostic failure never propagates into the native upload/ACK, camera, or answer path.
        } finally {
            synchronized (this) { ticket.query = null; }
        }
        synchronized (this) {
            if (!current(ticket)) return;
            if (outcome == null && ticket.reads < maxReads && nanos.getAsLong() - ticket.start < budgetNanos) {
                ticket.scheduled = worker.schedule(() -> read(ticket), intervalMillis, TimeUnit.MILLISECONDS);
            } else ticket.sink.accept(new Notice(ticket.binding, outcome == null ? Outcome.UNKNOWN : outcome));
        }
    }

    @Override public synchronized void close() { clear(); closed = true; worker.shutdownNow(); }

    private static String hash(Object value) throws JSONException {
        require(value instanceof String && ((String) value).matches("[0-9a-f]{64}")); return (String) value;
    }
    private static boolean integer(Object value, long expected) {
        return (value instanceof Integer || value instanceof Long) && ((Number) value).longValue() == expected;
    }
    private static void requireFalse(JSONObject value, String... keys) throws JSONException {
        for (String key : keys) require(Boolean.FALSE.equals(value.opt(key)));
    }
    private static void require(boolean valid) throws JSONException {
        if (!valid) throw new JSONException("撮影診断の対応を確認できません");
    }
}
