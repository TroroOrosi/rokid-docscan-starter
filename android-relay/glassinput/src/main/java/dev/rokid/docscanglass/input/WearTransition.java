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
 * <p>Folding the temple arms force-stops the process, so the first reading
 * after a start is a state to record, never a re-wear on its own.</p>
 */
public final class WearTransition {
    /** How long a new state must hold before it counts. */
    public static final long SETTLE_MILLIS = 1_000;

    /** Near-field threshold: below this the sensor is covered, so it is worn. */
    public static final float WORN_CENTIMETRES = 3f;

    private Boolean worn;
    private Boolean pending;
    private long pendingSinceMillis;

    /**
     * Feeds one reading.
     *
     * @return true exactly once per off-to-on crossing that settled.
     */
    public synchronized boolean onReading(float centimetres, long elapsedMillis) {
        boolean nowWorn = centimetres <= WORN_CENTIMETRES;
        if (worn == null) {
            // First reading after a start: record it, never act on it.
            worn = nowWorn;
            return false;
        }
        if (nowWorn == worn) {
            pending = null;
            return false;
        }
        if (pending == null || pending != nowWorn || elapsedMillis < pendingSinceMillis) {
            pending = nowWorn;
            pendingSinceMillis = elapsedMillis;
            return false;
        }
        if (elapsedMillis - pendingSinceMillis < SETTLE_MILLIS) {
            return false;
        }
        worn = nowWorn;
        pending = null;
        return nowWorn;
    }

    /** The last settled state, or null before the first reading. */
    public synchronized Boolean worn() {
        return worn;
    }
}
