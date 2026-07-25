package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CustomViewOpenTrackerTest {
    @Test
    public void oldOpenAckCannotAcknowledgeTheReplacementGeneration() {
        CustomViewOpenTracker tracker = new CustomViewOpenTracker();
        long first = tracker.requestOpen();
        long second = tracker.requestOpen();

        assertEquals(first, tracker.onOpened());
        assertFalse(tracker.isCurrentAcknowledged());
        assertEquals(second, tracker.onOpened());
        assertTrue(tracker.isCurrentAcknowledged(second));
    }

    @Test
    public void closeBeforeCurrentAckIsNeverAnAcknowledgedUserView() {
        CustomViewOpenTracker tracker = new CustomViewOpenTracker();
        tracker.requestOpen();
        tracker.requestOpen();

        assertFalse(tracker.isCurrentAcknowledged());
        tracker.onCurrentClosed();
        assertFalse(tracker.isCurrentAcknowledged());
    }

    @Test
    public void currentAsyncErrorClearsTheAcknowledgement() {
        CustomViewOpenTracker tracker = new CustomViewOpenTracker();
        long generation = tracker.requestOpen();
        assertEquals(generation, tracker.onOpened());
        assertTrue(tracker.isCurrentAcknowledged());

        assertEquals(generation, tracker.onError());
        assertFalse(tracker.isCurrentAcknowledged());
        assertTrue(tracker.isFaulted());
    }

    @Test(expected = IllegalStateException.class)
    public void asyncErrorFencesLaterRequestsInTheSameCallbackEpoch() {
        CustomViewOpenTracker tracker = new CustomViewOpenTracker();
        tracker.requestOpen();
        tracker.onError();

        tracker.requestOpen();
    }

    @Test
    public void rejectedOpenCannotBeAcknowledgedByALaterCallback() {
        CustomViewOpenTracker tracker = new CustomViewOpenTracker();
        long generation = tracker.requestOpen();
        tracker.rejectOpen(generation);

        assertEquals(CustomViewOpenTracker.NONE, tracker.onOpened());
        assertFalse(tracker.isCurrentAcknowledged());
        assertTrue(tracker.isFaulted());
    }

    @Test(expected = IllegalStateException.class)
    public void rejectedOpenFencesLaterRequestsInTheSameCallbackEpoch() {
        CustomViewOpenTracker tracker = new CustomViewOpenTracker();
        long rejected = tracker.requestOpen();
        tracker.rejectOpen(rejected);

        tracker.requestOpen();
    }

    @Test
    public void serviceRebindStartsAFreshRequestEpoch() {
        CustomViewOpenTracker tracker = new CustomViewOpenTracker();
        tracker.rejectOpen(tracker.requestOpen());

        tracker.reset();
        long next = tracker.requestOpen();
        assertFalse(tracker.isFaulted());
        assertEquals(next, tracker.onOpened());
        assertTrue(tracker.isCurrentAcknowledged(next));
    }
}
