package android.hardware.camera2;

import android.hardware.camera2.params.InputConfiguration;
import android.hardware.camera2.params.OutputConfiguration;
import android.os.Handler;
import android.view.Surface;
import java.util.List;
import java.util.function.IntFunction;

/** Test-only HAL boundary; CameraDevice's constructor is package-private. */
public final class DocScanTestCamera extends CameraDevice {
    public final TestSession session = new TestSession();
    public final IntFunction<CaptureRequest.Builder> requests;
    public StateCallback state;
    public Handler handler;
    public List<Surface> outputs;
    public int configurations;
    public boolean closed;
    public boolean refuseSession;

    public DocScanTestCamera(IntFunction<CaptureRequest.Builder> requests) { this.requests = requests; }
    @Override public String getId() { return "0"; }
    @Override public void close() {
        if (closed) return;
        closed = true;
        handler.post(() -> state.onClosed(this));
    }
    @Override public CaptureRequest.Builder createCaptureRequest(int template) { return requests.apply(template); }
    @Override public void createCaptureSession(List<Surface> surfaces, CameraCaptureSession.StateCallback callback, Handler h) {
        configurations++;
        outputs = surfaces;
        h.post(() -> { if (refuseSession) callback.onConfigureFailed(session); else callback.onConfigured(session); });
    }
    @Override public void createCaptureSessionByOutputConfigurations(List<OutputConfiguration> o, CameraCaptureSession.StateCallback c, Handler h) { throw new UnsupportedOperationException(); }
    @Override public void createConstrainedHighSpeedCaptureSession(List<Surface> o, CameraCaptureSession.StateCallback c, Handler h) { throw new UnsupportedOperationException(); }
    @Override public CaptureRequest.Builder createReprocessCaptureRequest(TotalCaptureResult r) { throw new UnsupportedOperationException(); }
    @Override public void createReprocessableCaptureSession(InputConfiguration i, List<Surface> o, CameraCaptureSession.StateCallback c, Handler h) { throw new UnsupportedOperationException(); }
    @Override public void createReprocessableCaptureSessionByConfigurations(InputConfiguration i, List<OutputConfiguration> o, CameraCaptureSession.StateCallback c, Handler h) { throw new UnsupportedOperationException(); }

    public final class TestSession extends CameraCaptureSession {
        public CaptureRequest repeating;
        public CaptureCallback previewCallback;
        public CaptureRequest captured;
        public CaptureCallback captureCallback;
        public int captures;
        public boolean closed;
        public boolean repeatingStopped;
        @Override public int setRepeatingRequest(CaptureRequest request, CaptureCallback callback, Handler h) {
            repeating = request; previewCallback = callback; return 1;
        }
        @Override public int capture(CaptureRequest request, CaptureCallback callback, Handler h) {
            captured = request; captureCallback = callback; captures++; return captures + 1;
        }
        @Override public void stopRepeating() { repeatingStopped = true; }
        @Override public void close() { closed = true; }
        @Override public CameraDevice getDevice() { return DocScanTestCamera.this; }
        @Override public Surface getInputSurface() { return null; }
        @Override public boolean isReprocessable() { return false; }
        @Override public void prepare(Surface s) { }
        @Override public void abortCaptures() { }
        @Override public int captureBurst(List<CaptureRequest> r, CaptureCallback c, Handler h) { throw new UnsupportedOperationException(); }
        @Override public int setRepeatingBurst(List<CaptureRequest> r, CaptureCallback c, Handler h) { throw new UnsupportedOperationException(); }
        @Override public void finalizeOutputConfigurations(List<OutputConfiguration> c) { }
    }
}
