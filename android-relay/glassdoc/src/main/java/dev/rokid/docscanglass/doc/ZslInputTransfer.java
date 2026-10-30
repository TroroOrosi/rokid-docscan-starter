package dev.rokid.docscanglass.doc;

import android.media.Image;
import android.media.ImageWriter;
import android.os.Handler;
import android.view.Surface;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.function.Consumer;

/** One input credit. Native queue/close never run on the camera callback handler. */
final class ZslInputTransfer implements AutoCloseable {
    interface Port extends AutoCloseable {
        void queue(Image image);
        void close();
    }
    interface Factory { Port create(Runnable released); }
    static Factory nativeWriter(Surface input, Handler handler) {
        return released -> {
            ImageWriter writer = ImageWriter.newInstance(input, 1);
            try { writer.setOnImageReleasedListener(ignored -> released.run(), handler); }
            catch (RuntimeException | OutOfMemoryError error) { writer.close(); throw error; }
            return new Port() {
                public void queue(Image image) { writer.queueInputImage(image); }
                public void close() { writer.close(); }
            };
        };
    }
    private final Executor worker;
    private final Handler handler;
    private final Consumer<String> failure;
    private Port port;
    private volatile boolean closed;
    private boolean initialized, busy, queued, released, closeCompleted;
    private Runnable idleChanged = () -> { };

    ZslInputTransfer(Executor worker, Handler handler, Factory factory, Consumer<String> failure) {
        this.worker = worker; this.handler = handler; this.failure = failure;
        worker.execute(() -> {
            try {
                port = factory.create(() -> handler.post(() -> {
                    if (!busy || closed) return;
                    released = true;
                    if (queued) { busy = false; idleChanged.run(); }
                }));
                handler.post(() -> initialized = !closed);
            } catch (RuntimeException | OutOfMemoryError error) { failed(error); }
        });
    }
    boolean ready() { return initialized && !closed && !busy; }
    boolean idle() { return closed ? closeCompleted : !busy; }
    void onIdle(Runnable callback) { idleChanged = callback; }

    /** A false return leaves ownership with the caller. */
    boolean queue(Image image, Runnable afterQueue) {
        if (!ready()) return false;
        busy = true; queued = false; released = false;
        worker.execute(() -> {
            if (closed) {
                try { image.close(); } catch (RuntimeException | OutOfMemoryError error) { failed(error); }
                return;
            }
            try {
                port.queue(image);
                // Success transfers ownership: ImageWriter has already invalidated the input.
                handler.post(() -> {
                    queued = true;
                    if (released) busy = false;
                    if (!closed) afterQueue.run();
                    if (!busy) idleChanged.run();
                });
            } catch (RuntimeException | OutOfMemoryError error) {
                try { image.close(); } catch (RuntimeException | OutOfMemoryError ignored) { }
                failed(error);
            }
        });
        return true;
    }
    private void failed(Throwable error) {
        handler.post(() -> { if (!closed) failure.accept("ZSL input " + error.getClass().getSimpleName()); });
    }
    @Override public void close() {
        close(() -> { }, () -> { });
    }
    void close(Runnable closeOwners, Runnable complete) {
        if (closed) return;
        closed = true;
        worker.execute(() -> {
            boolean completed = true;
            try { if (port != null) port.close(); }
            catch (RuntimeException | OutOfMemoryError error) {
                completed = false;
                handler.post(() -> failure.accept("ZSL close " + error.getClass().getSimpleName()));
            }
            try { closeOwners.run(); }
            catch (RuntimeException | OutOfMemoryError error) {
                completed = false;
                handler.post(() -> failure.accept("ZSL owners " + error.getClass().getSimpleName()));
            }
            finally {
                boolean finished = completed;
                handler.post(() -> { closeCompleted = finished; if (finished) { complete.run(); idleChanged.run(); } });
                if (worker instanceof ExecutorService service) service.shutdown();
            }
        });
    }
}
