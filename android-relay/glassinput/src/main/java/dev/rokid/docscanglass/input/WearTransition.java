package dev.rokid.docscanglass.input;

/**
 * Decides when the glasses were put back on, from the proximity sensor.
 *
 * <p>Measured 2026-09-10 on build {@code 1.25.015-20260903-150201}: the glasses
 * carry a sensortek {@code ucs_ucs146e0} proximity sensor in both a wakeup and
 * a non-wakeup form, so wear can be detected with no permission and no vendor
 * API. Near means worn.</p>
 *
 * <p>Only an off-then-on crossing counts. A session must not restart because
 * the sensor flickered while the glasses sat on a desk, and it must not restart
 * while they are still being worn -- {@code onWearingStatusNotify} on the phone
 * side reports the same state repeatedly. Both are why the transition is held
 * for {@link #SETTLE_MILLIS} before it is believed.</p>
 *
 * <p>The first near reading also settles. The caller decides whether this
 * initial synchronization still belongs to its bootstrap chooser.</p>
 */
public final class WearTransition {
    /** How long a new state must hold before it counts. */
    public static final long SETTLE_MILLIS = 1_000;

    /** Near-field threshold: below this the sensor is covered, so it is worn. */
    public static final float WORN_CENTIMETRES = 3f;

    private Boolean worn;
    private Boolean pending;
    private long pendingSinceMillis;
    private boolean initialWear;

    /**
     * Feeds one reading.
     *
     * @return true exactly once per off-to-on crossing that settled.
     */
    public synchronized boolean onReading(float centimetres, long elapsedMillis) {
        if (!Float.isFinite(centimetres) || centimetres < 0) return false;
        boolean nowWorn = centimetres <= WORN_CENTIMETRES;
        if (worn != null && nowWorn == worn) {
            pending = null;
            return false;
        }
        if (pending == null || pending != nowWorn || elapsedMillis < pendingSinceMillis) {
            pending = nowWorn;
            pendingSinceMillis = elapsedMillis;
            return false;
        }
        return confirm(elapsedMillis);
    }

    /** On-change sensors may emit only one sample; confirm that sample at its deadline. */
    public synchronized boolean confirm(long elapsedMillis) {
        if (pending == null || elapsedMillis < pendingSinceMillis
                || elapsedMillis - pendingSinceMillis < SETTLE_MILLIS) return false;
        initialWear = worn == null;
        worn = pending;
        pending = null;
        return worn;
    }

    public synchronized boolean initialWear() { return initialWear; }
    public synchronized long delayUntilSettled(long now) {
        return pending == null ? -1 : Math.max(0, SETTLE_MILLIS - Math.max(0, now - pendingSinceMillis));
    }

    /** The last settled state, or null before the first reading. */
    public synchronized Boolean worn() {
        return worn;
    }
}
