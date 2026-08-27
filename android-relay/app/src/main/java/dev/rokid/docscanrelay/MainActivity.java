package dev.rokid.docscanrelay;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Matrix;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.ArrayAdapter;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicLong;

/** Setup/status screen. Once connected, normal operation is driven by glasses. */
public final class MainActivity extends Activity
        implements RokidGlobalLink.Listener, DocScanController.Listener {
    private static final String TAG = "DocScanRokid";
    private static final int AUTH_REQUEST = 4027;
    private static final int PERMISSION_REQUEST = 4028;
    private static final long LEGACY_LONG_PRESS_MILLIS = 1200;
    private static final long INPUT_EVENT_DEBOUNCE_MILLIS = 350;
    private static final long SYSTEM_MENU_RECOVERY_DELAY_MILLIS = 650;
    private static final String PREF_ROTATION_INDEX = "rotation_index";

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final PressGestureInterpreter pressInterpreter =
            new PressGestureInterpreter(
                    LEGACY_LONG_PRESS_MILLIS,
                    INPUT_EVENT_DEBOUNCE_MILLIS);
    private final ExecutorService previewDecoder = Executors.newSingleThreadExecutor();
    private final AtomicLong previewGeneration = new AtomicLong();
    private final Runnable systemMenuRecovery = this::runSystemMenuRecovery;

    private void runSystemMenuRecovery() {
        if (destroyed || controller == null) {
            return;
        }
        // If no replacement CustomView opened during the recovery grace
        // period, the close belonged to navigation out of DocScan. Do not
        // replay that close later as a shutter or registration command.
        pressInterpreter.cancelPendingCustomViewExit();
        appendLog("Glasses system-menu exit -> restoring the current DocScan view");
        controller.restoreGlassesViewAfterMenuExit();
    }

    private RokidGlobalLink link;
    private JapaneseOcr ocr;
    private DocScanController controller;
    private EditText serverUrl;
    private EditText apiKey;
    private Spinner rotation;
    private EditText photoWidth;
    private EditText photoHeight;
    private EditText photoQuality;
    private TextView status;
    private TextView log;
    private ImageView capturePreview;
    private TextView capturePreviewMessage;
    private LinearLayout captureReviewActions;
    private Button autoCaptureButton;
    private Button confirmCaptureButton;
    private Button retakeCaptureButton;
    private Button discardCaptureButton;
    private Bitmap previewBitmap;
    private boolean awaitingPermission;
    private volatile boolean destroyed;
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        link = new RokidGlobalLink(this, this);
        ocr = new JapaneseOcr();
        controller = new DocScanController(this, link, ocr, this);
        setContentView(buildContentView());
        controller.showPendingCaptureReview();
    }

    private View buildContentView() {
        int pad = dp(16);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Rokid DocScan Relay");
        title.setTextSize(24);
        title.setTextColor(Color.BLACK);
        root.addView(title, matchWrap());

        TextView description = new TextView(this);
        description.setText(
                "推奨は「自動読取」です。開始すると1ページを3枚撮り、"
                        + "最も読めた1枚を自動で登録し、次のページへ進みます。"
                        + "グラス操作は要りません。読取完了だけこの画面で行います。\n"
                        + "手動時: グラスは1本指タップだけが届きます"
                        + "（長押しとダブルタップはOSが占有）。"
                        + "照準でタップ=シャッター。撮影確認画面は1回タップが届かないため"
                        + "（実機で `AI-exit` 非配送を確認）、撮り直しは2回タップ"
                        + "（デフォルト画面へ戻ると自動復帰して撮り直します）、"
                        + "登録は待機満了かこの画面のボタンです。");
        description.setTextSize(14);
        root.addView(description, matchWrap());

        serverUrl = new EditText(this);
        serverUrl.setHint("例: http://192.168.1.10:8000");
        serverUrl.setSingleLine(true);
        serverUrl.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        serverUrl.setText(getPreferences(MODE_PRIVATE)
                .getString("server_url", "http://192.168.1.10:8000"));
        root.addView(serverUrl, matchWrap());

        apiKey = new EditText(this);
        apiKey.setHint("ROKID_API_KEY（未設定なら空欄）");
        apiKey.setSingleLine(true);
        apiKey.setInputType(
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(apiKey, matchWrap());

        rotation = new Spinner(this);
        rotation.setAdapter(new ArrayAdapter<>(
                this,
                android.R.layout.simple_spinner_dropdown_item,
                new String[]{"写真回転 0°", "写真回転 90°", "写真回転 180°", "写真回転 270°"}));
        rotation.setSelection(getPreferences(MODE_PRIVATE)
                .getInt(PREF_ROTATION_INDEX, 1));
        root.addView(rotation, matchWrap());

        // The usable capture size is firmware-dependent and has to be probed on
        // the device; keeping it editable here means a sweep costs a button
        // press instead of a reinstall and a fresh Hi Rokid authorization.
        PhotoCaptureSettings initial = controller.captureSettings();
        photoWidth = numberField("幅", initial.width);
        photoHeight = numberField("高さ", initial.height);
        photoQuality = numberField("品質", initial.quality);
        LinearLayout captureSettingsRow = horizontalRow();
        captureSettingsRow.addView(photoWidth, weighted());
        captureSettingsRow.addView(photoHeight, weighted());
        captureSettingsRow.addView(photoQuality, weighted());
        root.addView(captureSettingsRow, matchWrap());

        LinearLayout captureSettingsActions = horizontalRow();
        captureSettingsActions.addView(
                button("撮影設定を適用", ignored -> applyCaptureSettings()), weighted());
        captureSettingsActions.addView(
                button("次のプリセット", ignored -> applyNextCapturePreset()), weighted());
        root.addView(captureSettingsActions, matchWrap());

        LinearLayout connectRow = horizontalRow();
        connectRow.addView(button("サーバ確認", ignored -> configureAndVerify()), weighted());
        connectRow.addView(
                button("Hi Rokid認可・再接続", ignored -> authorizeAndConnect()), weighted());
        root.addView(connectRow, matchWrap());

        // The capture-review CustomView swallows taps: it closes without
        // delivering any AI event. Hands-free reading is therefore the primary
        // way to get pages in, and the manual row below stays for diagnosis.
        LinearLayout autoRow = horizontalRow();
        autoCaptureButton = button("自動読取 開始", ignored -> toggleAutoCapture());
        autoRow.addView(autoCaptureButton, weighted());
        root.addView(autoRow, matchWrap());

        LinearLayout captureRow = horizontalRow();
        captureRow.addView(
                button("撮影準備", ignored -> controller.captureNextPage()), weighted());
        captureRow.addView(
                button(
                        "前ページ撮影準備",
                        ignored -> controller.recapturePreviousPage()),
                weighted());
        captureRow.addView(button("読取完了", ignored -> controller.finishReading()), weighted());

        // The glasses can only deliver a tap, so every action they cannot reach
        // needs a phone control. The shutter is duplicated rather than moved:
        // during aiming the operator is holding the page and should not have to
        // reach for the phone at all.
        LinearLayout shutterRow = horizontalRow();
        shutterRow.addView(
                button("シャッター", ignored -> controller.triggerArmedCapture()),
                weighted());
        shutterRow.addView(
                button("撮影取消", ignored -> controller.cancelAiming()), weighted());
        root.addView(shutterRow, matchWrap());
        root.addView(captureRow, matchWrap());

        LinearLayout reviewRow = horizontalRow();
        reviewRow.addView(button("戻る", ignored -> controller.previousReviewItem()), weighted());
        reviewRow.addView(button("次へ", ignored -> controller.nextReviewItem()), weighted());
        reviewRow.addView(button("新規", ignored -> controller.startNewDocument()), weighted());
        root.addView(reviewRow, matchWrap());

        TextView captureGuide = new TextView(this);
        captureGuide.setText(
                "固定焦点・ライブ映像なし: 用紙を40〜60cm離し、中心を＋へ合わせます。"
                        + "照準でタップした後は1.5秒静止し、"
                        + "撮影後に四隅と文字の輪郭を確認してください。");
        captureGuide.setTextSize(14);
        captureGuide.setPadding(0, dp(8), 0, dp(8));
        root.addView(captureGuide, matchWrap());

        capturePreview = new ImageView(this);
        capturePreview.setAdjustViewBounds(true);
        capturePreview.setScaleType(ImageView.ScaleType.FIT_CENTER);
        capturePreview.setBackgroundColor(Color.DKGRAY);
        capturePreview.setVisibility(View.GONE);
        root.addView(capturePreview, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(280)));

        capturePreviewMessage = new TextView(this);
        capturePreviewMessage.setTextSize(15);
        capturePreviewMessage.setPadding(0, dp(8), 0, dp(4));
        capturePreviewMessage.setVisibility(View.GONE);
        root.addView(capturePreviewMessage, matchWrap());

        captureReviewActions = horizontalRow();
        confirmCaptureButton =
                button("この写真を登録", ignored -> controller.confirmPendingCapture());
        retakeCaptureButton =
                button(
                        "同じページを撮り直す",
                        ignored -> controller.retakePendingCapture(
                                rotation.getSelectedItemPosition() * 90));
        discardCaptureButton =
                button("未登録写真を破棄", ignored -> controller.discardPendingCapture());
        captureReviewActions.addView(confirmCaptureButton, weighted());
        captureReviewActions.addView(retakeCaptureButton, weighted());
        captureReviewActions.addView(discardCaptureButton, weighted());
        captureReviewActions.setVisibility(View.GONE);
        root.addView(captureReviewActions, matchWrap());

        status = new TextView(this);
        status.setText("DISCONNECTED");
        status.setTextSize(18);
        status.setPadding(0, dp(12), 0, dp(6));
        root.addView(status, matchWrap());

        log = new TextView(this);
        log.setTextSize(12);
        log.setTextIsSelectable(true);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(log, matchWrap());
        // A fixed height instead of a weight: inside the outer page scroller
        // there is no leftover space to weight against, and on the F-51F the
        // weighted log collapsed to zero height as soon as the capture preview
        // became visible, taking the status line off-screen with it.
        root.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(180)));

        // targetSdk 36 means Android 15+ forces edge-to-edge, so the status
        // bar covers the title and the navigation bar covers the capture
        // review buttons unless the insets are applied here. The page also has
        // to scroll: with the preview shown the content is taller than the
        // screen, and a clipped status line leaves the operator no feedback.
        ScrollView page = new ScrollView(this);
        page.setFillViewport(true);
        page.addView(root, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT));
        page.setOnApplyWindowInsetsListener((view, insets) -> {
            Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        return page;
    }

    private EditText numberField(String hint, int value) {
        EditText field = new EditText(this);
        field.setHint(hint);
        field.setSingleLine(true);
        field.setInputType(InputType.TYPE_CLASS_NUMBER);
        field.setText(String.valueOf(value));
        return field;
    }

    private void applyCaptureSettings() {
        PhotoCaptureSettings settings;
        try {
            settings = PhotoCaptureSettings.parse(
                    photoWidth.getText().toString(),
                    photoHeight.getText().toString(),
                    photoQuality.getText().toString());
        } catch (IllegalArgumentException error) {
            showError(error.getMessage());
            return;
        }
        applyCaptureSettings(settings);
    }

    private void applyNextCapturePreset() {
        applyCaptureSettings(
                PhotoCaptureSettings.nextPreset(controller.captureSettings()));
    }

    private void applyCaptureSettings(PhotoCaptureSettings settings) {
        try {
            controller.applyCaptureSettings(settings);
        } catch (IllegalStateException error) {
            showError(error.getMessage());
            return;
        }
        showCaptureSettings(settings);
        appendLog("撮影設定 " + settings.describe());
        Toast.makeText(this, "撮影設定 " + settings.describe(), Toast.LENGTH_SHORT).show();
    }

    private void showCaptureSettings(PhotoCaptureSettings settings) {
        photoWidth.setText(String.valueOf(settings.width));
        photoHeight.setText(String.valueOf(settings.height));
        photoQuality.setText(String.valueOf(settings.quality));
    }

    private void configureAndVerify() {
        if (!configureController()) {
            return;
        }
        controller.verifyServer();
    }

    private void authorizeAndConnect() {
        boolean captureRecovery = controller.isCaptureReconnectRequired();
        boolean preservePendingReview = controller.hasPendingCaptureReview();
        if (!captureRecovery && !configureController()) {
            return;
        }
        if (captureRecovery || preservePendingReview) {
            appendLog(
                    (captureRecovery
                            ? "Capture completion is unknown"
                            : "An unregistered photo is awaiting confirmation")
                            + "; reconnecting without changing the current server configuration.");
        }
        if (!RokidGlobalLink.isGlobalHiRokidInstalled(this)) {
            showError("グローバル版Hi Rokidがスマホにインストールされていません");
            return;
        }
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                != PackageManager.PERMISSION_GRANTED) {
            awaitingPermission = true;
            requestPermissions(
                    new String[]{Manifest.permission.BLUETOOTH_CONNECT},
                    PERMISSION_REQUEST);
            return;
        }
        launchAuthorization();
    }

    private boolean configureController() {
        try {
            String server = serverUrl.getText().toString().trim();
            int rotationDegrees = rotation.getSelectedItemPosition() * 90;
            controller.configure(server, apiKey.getText().toString(), rotationDegrees);
            getPreferences(MODE_PRIVATE).edit()
                    .putString("server_url", server)
                    .putInt(PREF_ROTATION_INDEX, rotation.getSelectedItemPosition())
                    .apply();
            return true;
        } catch (RuntimeException error) {
            showError(error.getMessage());
            return false;
        }
    }

    private void launchAuthorization() {
        try {
            startActivityForResult(
                    RokidGlobalLink.authorizationIntent(this),
                    AUTH_REQUEST);
        } catch (RuntimeException error) {
            showError("Hi Rokid認可画面を開けません: " + error.getMessage());
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != PERMISSION_REQUEST || !awaitingPermission) {
            return;
        }
        awaitingPermission = false;
        if (grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            launchAuthorization();
        } else {
            showError("Bluetooth接続権限が必要です");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != AUTH_REQUEST) {
            return;
        }
        String token = RokidGlobalLink.authorizationToken(resultCode, data);
        if (token == null) {
            showError("Hi Rokidの認可がキャンセルまたは拒否されました");
            return;
        }
        appendLog(
                "Authorization succeeded; resetting the CXR-L binding without logging the token.");
        // A fresh authorization is also the user-visible recovery path after
        // a photo timeout. An actual unbind clears both capture guards before
        // the replacement service can report itself ready.
        link.close();
        link.connect(token);
    }

    @Override
    public void onLinkConnected(boolean connected) {
        String identity = link.serviceIdentity();
        runOnUiThread(() -> appendLog(
                "Hi Rokid service connected=" + connected + " " + identity));
    }

    @Override
    public void onCaptureLinkStateChanged(
            boolean connected,
            CaptureLinkEvent event
    ) {
        controller.onCaptureLinkStateChanged(connected, event);
        runOnUiThread(() -> appendLog(
                "Rokid Glasses connected=" + connected + " event=" + event));
    }

    @Override
    public void onAiPressDown() {
        PressGestureInterpreter.Action action =
                pressInterpreter.onAiAssistStart(SystemClock.elapsedRealtime());
        runOnUiThread(() -> appendLog(
                action == null
                        ? "Glasses input source=AI-assist-start (duplicate ignored)"
                        : "Glasses input source=AI-assist-start -> LONG"));
        if (action != null) {
            dispatchGesture(action);
        }
    }

    @Override
    public void onAiPressUp() {
        runOnUiThread(() -> appendLog(
                "Glasses AI-key-up observed; no destructive action is assigned"));
    }

    @Override
    public void onAiExit() {
        // YodaOS reserves long press and double tap, and this firmware delivers
        // neither AI key down/up nor a user-initiated CustomView close, so a
        // single tap surfacing as this callback is the only glasses input the
        // relay receives. Only the non-destructive short action is derived.
        PressGestureInterpreter.Action action =
                pressInterpreter.onAiExit(SystemClock.elapsedRealtime());
        mainHandler.removeCallbacks(systemMenuRecovery);
        mainHandler.postDelayed(
                systemMenuRecovery,
                SYSTEM_MENU_RECOVERY_DELAY_MILLIS);
        runOnUiThread(() -> appendLog(
                action == null
                        ? "Glasses AI-exit echoed our own view push; no input"
                        : "Glasses input source=AI-exit tap -> " + action));
        if (action != null) {
            dispatchGesture(action);
        }
    }

    @Override
    public void onGlassesViewPushed() {
        pressInterpreter.onGlassesViewOperation(SystemClock.elapsedRealtime());
    }

    @Override
    public void onCustomViewClosedByUser() {
        dispatchDiscreteGlassesAction("user CustomView close");
    }

    @Override
    public void onCustomViewAvailable(long generation, String purpose) {
        pressInterpreter.onGlassesViewOpened(SystemClock.elapsedRealtime());
        mainHandler.removeCallbacks(systemMenuRecovery);
        controller.onCustomViewAvailable(generation, purpose);
        runOnUiThread(() -> appendLog(
                "Glasses DocScan view available generation=" + generation
                        + " purpose=" + purpose
                        + "; system-menu recovery cancelled"));
    }

    @Override
    public void onCustomViewFailed(
            long generation,
            String purpose,
            String message,
            Throwable cause
    ) {
        mainHandler.removeCallbacks(systemMenuRecovery);
        controller.onCustomViewFailed(generation, purpose, message, cause);
        runOnUiThread(() -> appendLog(
                "Glasses DocScan view failed generation=" + generation
                        + " purpose=" + purpose
                        + ": " + message));
    }

    private void dispatchDiscreteGlassesAction(String source) {
        PressGestureInterpreter.Action immediate =
                pressInterpreter.onCustomViewExit(SystemClock.elapsedRealtime());
        runOnUiThread(() -> appendLog(
                "Glasses input source=" + source
                        + (immediate == null ? " (SHORT pending/coalesced)" : " -> " + immediate)));
        if (immediate != null) {
            dispatchGesture(immediate);
            return;
        }
        mainHandler.postDelayed(() -> {
            PressGestureInterpreter.Action delayed =
                    pressInterpreter.flush(SystemClock.elapsedRealtime());
            if (delayed != null) {
                appendLog("Glasses input -> " + delayed);
                dispatchGesture(delayed);
            }
        }, LEGACY_LONG_PRESS_MILLIS + INPUT_EVENT_DEBOUNCE_MILLIS + 20);
    }

    private void dispatchGesture(PressGestureInterpreter.Action action) {
        controller.onGlassesGesture(action);
    }

    @Override
    public void onPhoto(byte[] jpeg) {
        controller.onPhoto(jpeg);
    }

    @Override
    public void onPhotoError(String message, Throwable cause) {
        controller.onPhotoError(message, cause);
        onError(message, cause);
    }

    @Override
    public void onError(String message, Throwable cause) {
        String detail = cause == null ? message : message + ": " + cause.getMessage();
        runOnUiThread(() -> {
            appendLog(detail);
            Toast.makeText(this, message, Toast.LENGTH_LONG).show();
        });
    }

    @Override
    public void onUpdate(RelayState next, List<String> hudLines, String diagnostic) {
        runOnUiThread(() -> {
            status.setText(next.name() + " — " + String.join(" / ", hudLines));
            if (captureReviewActions.getVisibility() == View.VISIBLE) {
                boolean decisionEnabled = next == RelayState.CAPTURE_REVIEW;
                confirmCaptureButton.setEnabled(decisionEnabled);
                retakeCaptureButton.setEnabled(decisionEnabled);
                discardCaptureButton.setEnabled(decisionEnabled);
            }
            appendLog(diagnostic);
        });
    }

    @Override
    public void onCaptureReview(CaptureReviewStore.Pending pending) {
        long generation = previewGeneration.incrementAndGet();
        try {
            previewDecoder.execute(() -> {
                Bitmap bitmap = decodeCapturePreview(
                        pending.jpeg, pending.rotationDegrees, 1200);
                runOnUiThread(() -> {
                    if (destroyed || previewGeneration.get() != generation) {
                        if (bitmap != null) {
                            bitmap.recycle();
                        }
                        return;
                    }
                    replacePreviewBitmap(bitmap);
                    String warning = pending.ocrCharacters() == 0
                            ? "警告: OCRは0文字です。"
                            : "OCR: " + pending.ocrCharacters() + "文字。";
                    if (pending.hasOcrFailure()) {
                        warning += " OCR処理エラーも発生しました。";
                    }
                    // The framing verdict is what the operator cannot judge
                    // from the glasses, so it leads the message and names the
                    // recommended action outright.
                    String verdict = pending.isFramingFailing()
                            ? "判定: 不合格 — " + pending.framing.describe()
                                    + "。撮り直しを推奨します。"
                            : "判定: " + pending.framing.describe() + "。";
                    capturePreviewMessage.setText(
                            "P" + (pending.pageIndex + 1) + "（まだ未登録）— "
                                    + verdict + " " + warning
                                    + "\nグラスの表示が出てから一定時間で自動登録します。"
                                    + "撮り直すならグラスを2回タップしてください"
                                    + "（デフォルト画面へ戻ると自動で復帰し、撮り直します）。"
                                    + "\n用紙の四隅と文字の輪郭を確認し、登録か撮り直しを選んでください。");
                    capturePreview.setVisibility(bitmap == null ? View.GONE : View.VISIBLE);
                    capturePreviewMessage.setVisibility(View.VISIBLE);
                    captureReviewActions.setVisibility(View.VISIBLE);
                    boolean decisionEnabled =
                            controller.getState() == RelayState.CAPTURE_REVIEW;
                    confirmCaptureButton.setEnabled(decisionEnabled);
                    retakeCaptureButton.setEnabled(decisionEnabled);
                    discardCaptureButton.setEnabled(decisionEnabled);
                });
            });
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    private void toggleAutoCapture() {
        if (controller.isAutoCaptureEnabled()) {
            controller.stopAutoCapture();
        } else {
            controller.startAutoCapture();
        }
    }

    @Override
    public void onAutoCaptureChanged(boolean running) {
        runOnUiThread(() -> {
            if (autoCaptureButton != null) {
                autoCaptureButton.setText(running ? "自動読取 停止" : "自動読取 開始");
            }
            appendLog(running
                    ? "Automatic reading started"
                    : "Automatic reading stopped");
        });
    }

    @Override
    public void onCaptureReviewCleared() {
        previewGeneration.incrementAndGet();
        runOnUiThread(this::clearCapturePreview);
    }

    private static Bitmap decodeCapturePreview(
            byte[] jpeg,
            int rotationDegrees,
            int maxDimension
    ) {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, bounds);
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            return null;
        }
        int sample = 1;
        while (Math.max(bounds.outWidth, bounds.outHeight) / sample > maxDimension) {
            sample *= 2;
        }
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sample;
        Bitmap decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options);
        if (decoded == null || rotationDegrees == 0) {
            return decoded;
        }
        Matrix matrix = new Matrix();
        matrix.postRotate(rotationDegrees);
        Bitmap rotated = Bitmap.createBitmap(
                decoded, 0, 0, decoded.getWidth(), decoded.getHeight(), matrix, true);
        if (rotated != decoded) {
            decoded.recycle();
        }
        return rotated;
    }

    private void replacePreviewBitmap(Bitmap bitmap) {
        capturePreview.setImageDrawable(null);
        if (previewBitmap != null) {
            previewBitmap.recycle();
        }
        previewBitmap = bitmap;
        capturePreview.setImageBitmap(bitmap);
    }

    private void clearCapturePreview() {
        capturePreview.setImageDrawable(null);
        if (previewBitmap != null) {
            previewBitmap.recycle();
            previewBitmap = null;
        }
        capturePreview.setVisibility(View.GONE);
        capturePreviewMessage.setVisibility(View.GONE);
        captureReviewActions.setVisibility(View.GONE);
    }

    private void appendLog(String message) {
        // Mirrored to logcat so a real-device run leaves a trace that survives
        // the activity. Only the structural diagnostics reach this method; HUD
        // lines carrying page content go to the status view and stay there.
        Log.i(TAG, message);
        String current = log.getText().toString();
        log.setText(current + (current.isEmpty() ? "" : "\n") + message);
    }

    private void showError(String message) {
        appendLog("ERROR: " + message);
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
    }

    private Button button(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setOnClickListener(listener);
        return button;
    }

    private LinearLayout horizontalRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        return row;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams weighted() {
        return new LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        previewGeneration.incrementAndGet();
        previewDecoder.shutdownNow();
        clearCapturePreview();
        mainHandler.removeCallbacksAndMessages(null);
        pressInterpreter.cancel();
        link.close();
        controller.close();
        ocr.close();
        super.onDestroy();
    }
}
