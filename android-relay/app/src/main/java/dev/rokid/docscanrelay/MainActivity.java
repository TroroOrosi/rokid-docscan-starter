package dev.rokid.docscanrelay;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.ArrayAdapter;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

/** Setup/status screen. Once connected, normal operation is driven by glasses. */
public final class MainActivity extends Activity
        implements RokidGlobalLink.Listener, DocScanController.Listener {
    private static final int AUTH_REQUEST = 4027;
    private static final int PERMISSION_REQUEST = 4028;
    private static final long LONG_PRESS_MILLIS = 1200;
    private static final long DOUBLE_PRESS_MILLIS = 350;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final PressGestureInterpreter pressInterpreter =
            new PressGestureInterpreter(LONG_PRESS_MILLIS, DOUBLE_PRESS_MILLIS);

    private RokidGlobalLink link;
    private JapaneseOcr ocr;
    private DocScanController controller;
    private EditText serverUrl;
    private EditText apiKey;
    private Spinner rotation;
    private TextView status;
    private TextView log;
    private boolean awaitingPermission;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        link = new RokidGlobalLink(this, this);
        ocr = new JapaneseOcr();
        controller = new DocScanController(this, link, ocr, this);
        setContentView(buildContentView());
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
                "設定後はこの画面を表示したままにします。"
                        + "短押し=撮影/次へ、2回押し=再撮影/戻る、長押し=読取完了/終了。");
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
        root.addView(rotation, matchWrap());

        LinearLayout connectRow = horizontalRow();
        connectRow.addView(button("サーバ確認", ignored -> configureAndVerify()), weighted());
        connectRow.addView(button("Hi Rokid認可・接続", ignored -> authorizeAndConnect()), weighted());
        root.addView(connectRow, matchWrap());

        LinearLayout captureRow = horizontalRow();
        captureRow.addView(button("撮影", ignored -> controller.captureNextPage()), weighted());
        captureRow.addView(button("前ページ再撮影", ignored -> controller.recapturePreviousPage()), weighted());
        captureRow.addView(button("読取完了", ignored -> controller.finishReading()), weighted());
        root.addView(captureRow, matchWrap());

        LinearLayout reviewRow = horizontalRow();
        reviewRow.addView(button("戻る", ignored -> controller.previousReviewItem()), weighted());
        reviewRow.addView(button("次へ", ignored -> controller.nextReviewItem()), weighted());
        reviewRow.addView(button("新規", ignored -> controller.startNewDocument()), weighted());
        root.addView(reviewRow, matchWrap());

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
        root.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        return root;
    }

    private void configureAndVerify() {
        if (!configureController()) {
            return;
        }
        controller.verifyServer();
    }

    private void authorizeAndConnect() {
        if (!configureController()) {
            return;
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
            getPreferences(MODE_PRIVATE).edit().putString("server_url", server).apply();
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
        appendLog("Authorization succeeded; connecting without logging the token.");
        link.connect(token);
    }

    @Override
    public void onLinkConnected(boolean connected) {
        runOnUiThread(() -> appendLog("Hi Rokid service connected=" + connected));
        if (!connected) {
            controller.setLinkReady(false);
        }
    }

    @Override
    public void onGlassesConnected(boolean connected) {
        controller.setLinkReady(connected);
        runOnUiThread(() -> appendLog("Rokid Glasses connected=" + connected));
    }

    @Override
    public void onAiPressDown() {
        pressInterpreter.onDown(SystemClock.elapsedRealtime());
    }

    @Override
    public void onAiPressUp() {
        long now = SystemClock.elapsedRealtime();
        PressGestureInterpreter.Action immediate = pressInterpreter.onUp(now);
        if (immediate != null) {
            dispatchGesture(immediate);
            return;
        }
        mainHandler.postDelayed(() -> {
            PressGestureInterpreter.Action delayed =
                    pressInterpreter.flush(SystemClock.elapsedRealtime());
            if (delayed != null) {
                dispatchGesture(delayed);
            }
        }, DOUBLE_PRESS_MILLIS + 20);
    }

    private void dispatchGesture(PressGestureInterpreter.Action action) {
        RelayState current = controller.getState();
        switch (action) {
            case SHORT:
                if (current == RelayState.REVIEW) {
                    controller.nextReviewItem();
                } else {
                    controller.captureNextPage();
                }
                break;
            case DOUBLE_SHORT:
                if (current == RelayState.REVIEW) {
                    controller.previousReviewItem();
                } else {
                    controller.recapturePreviousPage();
                }
                break;
            case LONG:
                if (current == RelayState.REVIEW) {
                    controller.startNewDocument();
                } else {
                    controller.finishReading();
                }
                break;
            default:
                break;
        }
    }

    @Override
    public void onPhoto(byte[] jpeg) {
        controller.onPhoto(jpeg);
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
            appendLog(diagnostic);
        });
    }

    private void appendLog(String message) {
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
        mainHandler.removeCallbacksAndMessages(null);
        pressInterpreter.cancel();
        controller.close();
        ocr.close();
        link.close();
        super.onDestroy();
    }
}
