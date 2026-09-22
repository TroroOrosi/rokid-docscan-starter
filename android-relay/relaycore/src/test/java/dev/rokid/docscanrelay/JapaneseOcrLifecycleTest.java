package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import android.graphics.Bitmap;
import android.content.Context;
import android.content.pm.ServiceInfo;
import android.os.Bundle;
import com.google.mlkit.common.sdkinternal.MlKitContext;
import com.google.android.gms.tasks.TaskCompletionSource;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognizer;
import java.io.ByteArrayOutputStream;
import java.lang.reflect.Proxy;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import static org.robolectric.Shadows.shadowOf;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.shadows.ShadowLooper;
import org.robolectric.util.ReflectionHelpers;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public class JapaneseOcrLifecycleTest {
    @Before public void initializeSdkContextWithoutStartingRecognition() {
        // Config.NONE omits manifest providers/registrars. InputImage itself logs
        // through ML Kit, even with a fake recognizer. Supply its real common
        // components rather than shadowing bitmap lifetime or weakening assertions.
        Context context = RuntimeEnvironment.getApplication();
        ServiceInfo service = new ServiceInfo();
        service.packageName = context.getPackageName();
        service.name = "com.google.mlkit.common.internal.MlKitComponentDiscoveryService";
        service.metaData = new Bundle();
        service.metaData.putString(
                "com.google.firebase.components:com.google.mlkit.common.internal.CommonComponentRegistrar",
                "com.google.firebase.components.ComponentRegistrar");
        shadowOf(context.getPackageManager()).addOrUpdateService(service);
        MlKitContext.initializeIfNeeded(context);
    }

    @Test public void chooserDoesNotInitializeRecognizerAndCloseIsIdempotent() {
        JapaneseOcr ocr = new JapaneseOcr();
        assertNull(ReflectionHelpers.getField(ocr, "recognizer"));
        ocr.close(); ocr.close();
    }
    @Test public void asyncFailureReleasesInputBeforeDownstreamCallback() {
        runFailure(false);
    }
    @Test public void synchronousProcessFailureAlsoReleasesInputBeforeCallback() {
        runFailure(true);
    }
    private static void runFailure(boolean synchronous) {
        JapaneseOcr ocr = new JapaneseOcr();
        TaskCompletionSource<Text> result = new TaskCompletionSource<>();
        AtomicReference<Bitmap> input = new AtomicReference<>();
        AtomicInteger callbacks = new AtomicInteger();
        TextRecognizer fake = (TextRecognizer) Proxy.newProxyInstance(
                TextRecognizer.class.getClassLoader(), new Class<?>[]{TextRecognizer.class}, (proxy, method, args) -> {
                    if ("process".equals(method.getName())) {
                        input.set(((InputImage) args[0]).getBitmapInternal());
                        if (synchronous) throw new IllegalStateException("synthetic failure");
                        return result.getTask();
                    }
                    return null;
                });
        ReflectionHelpers.setField(ocr, "recognizer", fake);
        Bitmap bitmap = Bitmap.createBitmap(80, 120, Bitmap.Config.RGB_565);
        ByteArrayOutputStream jpeg = new ByteArrayOutputStream();
        bitmap.compress(Bitmap.CompressFormat.JPEG, 80, jpeg); bitmap.recycle();
        ocr.recognize(jpeg.toByteArray(), 270, new JapaneseOcr.Callback() {
            public void onResult(String text, OcrQuality quality, PageFraming framing) { fail("unexpected success"); }
            public void onError(Throwable error) {
                if (input.get() == null) throw new AssertionError("InputImage setup failed before recognizer.process", error);
                assertTrue("OCR pixels must be freed before next-stage work", input.get().isRecycled());
                callbacks.incrementAndGet();
            }
        });
        if (!synchronous) {
            assertFalse(input.get().isRecycled());
            result.setException(new IllegalStateException("synthetic failure"));
            ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
        }
        assertEquals(1, callbacks.get());
        ocr.close();
    }
}
