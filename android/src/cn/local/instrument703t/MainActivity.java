package cn.local.instrument703t;
import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable refresh = new Runnable() { public void run() { render(); handler.postDelayed(this, 400); } };
    private static final int PICK = 10, EXPORT = 11, PERMISSIONS = 12;
    private static final int SCAN_WIFI = 13;
    private static final int INK = 0xff182f36, MUTED = 0xff586e75, TEAL = 0xff096e73;
    private TextView packageText, wifiText, stateText, versionText;
    private ProgressBar bar;
    private Button choose, scan, join, adopt, read, start, stop;
    private Runnable pendingWifi;
    private String last = "";
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); Store.restore(this);
        try { BundledTrust.initialize(this); } catch (Exception e) { Store.status(this, "ERROR", "内置发布公钥不可用，请重新安装可信 APK。", 0); }
        getWindow().setStatusBarColor(0xffedf4f3); getWindow().setNavigationBarColor(0xffedf4f3);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setBackgroundColor(0xffedf4f3);
        LinearLayout page = column(); page.setPadding(dp(18), dp(20), dp(18), dp(20)); scroll.addView(page); setContentView(scroll);
        page.addView(text("703T 仪表 OTA", 27, INK, true));
        TextView subtitle = text("全量固件 · 文件增量", 14, MUTED, false); page.addView(subtitle); gap(subtitle, 6, 16);
        LinearLayout files = card(page, "选择固件");
        packageText = text("选择原厂全量 TAR，或带签名、测试及回退脚本的增量 TAR。", 14, INK, false); files.addView(packageText);
        choose = button("选择固件 TAR", true, v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), PICK)); files.addView(choose); gap(choose, 14, 0);
        LinearLayout network = card(page, "连接仪表热点"); wifiText = text("尚未连接 Wi-Fi", 14, INK, false); network.addView(wifiText);
        scan = button("扫描仪表二维码", true, v -> scanWifi());
        network.addView(scan); gap(scan, 8, 0);
        join = button("手动连接", false, v -> permissions(this::wifiDialog));
        adopt = button("使用当前 Wi-Fi", false, v -> permissions(() -> { try { WifiLink.adopt(this); render(); } catch (Exception e) { error(e); } }));
        LinearLayout wifiButtons = new LinearLayout(this); wifiButtons.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams first = new LinearLayout.LayoutParams(0, -2, 1); first.setMarginEnd(dp(8)); wifiButtons.addView(join, first);
        wifiButtons.addView(adopt, new LinearLayout.LayoutParams(0, -2, 1)); network.addView(wifiButtons); gap(wifiButtons, 8, 0);
        LinearLayout operation = card(page, "开始更新");
        versionText = text("连接后读取仪表型号、版本，再发送固件。", 13, MUTED, false); operation.addView(versionText);
        stateText = text(Store.message, 14, INK, false); operation.addView(stateText); gap(stateText, 12, 10);
        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); bar.setMax(100); bar.setProgressTintList(android.content.res.ColorStateList.valueOf(TEAL)); operation.addView(bar);
        start = button("开始 OTA", true, v -> confirm(true)); operation.addView(start); gap(start, 14, 6);
        read = button("读取仪表版本", false, v -> confirm(false)); operation.addView(read);
        stop = button("停止传输", false, v -> UpdateService.cancelTransfer()); operation.addView(stop); gap(stop, 6, 0);
        page.addView(button("使用说明", false, v -> new AlertDialog.Builder(this).setTitle("使用说明")
                .setMessage("1. 选择固件并等待校验，再扫描仪表投屏页的 Wi-Fi 二维码，按系统提示连接。发布公钥已内置。\n\n2. 开始 OTA 后，会连续完成版本检查、文件传输及安装请求。增量只匹配包内指定的仪表版本。\n\n3. 连接升级端口会停止 DVR 和部分投屏进程。请停车、保持稳定供电。\n\n4. 原厂协议没有可靠续传或安装结果查询。文件传完不等于安装成功，最终请看仪表。增量测试和回退由包内脚本执行。\n\n当前协议来自固件静态分析，尚未完成实机验证。")
                .setPositiveButton("知道了", null).show()));
        page.addView(button("导出日志", false, v -> startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("text/plain").putExtra(Intent.EXTRA_TITLE, "703T-ota-log.txt"), EXPORT)));
        render();
    }
    @Override protected void onResume() { super.onResume(); handler.post(refresh); }
    @Override protected void onPause() { handler.removeCallbacks(refresh); super.onPause(); }
    private int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density + .5f); }
    private LinearLayout column() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); return l; }
    private TextView text(String value, int size, int color, boolean bold) { TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setLineSpacing(dp(3), 1); if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD); return t; }
    private void gap(View v, int top, int bottom) { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.topMargin = dp(top); p.bottomMargin = dp(bottom); v.setLayoutParams(p); }
    private LinearLayout card(LinearLayout parent, String title) {
        LinearLayout l = column(); l.setPadding(dp(14), dp(14), dp(14), dp(14)); GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.WHITE); bg.setCornerRadius(dp(16)); l.setBackground(bg);
        TextView heading = text(title, 19, INK, true); l.addView(heading); gap(heading, 0, 8); parent.addView(l); gap(l, 0, 12); return l;
    }
    private Button button(String label, boolean primary, View.OnClickListener action) {
        Button b = new Button(this); b.setText(label); b.setTextSize(14); b.setAllCaps(false); b.setMinHeight(dp(48)); b.setTextColor(primary ? Color.WHITE : TEAL);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(primary ? TEAL : 0xffe6f1f0)); b.setOnClickListener(action); return b;
    }
    private void enable(Button b, boolean enabled) { b.setEnabled(enabled); b.setAlpha(enabled ? 1 : .4f); }
    private void render() {
        if (packageText == null) return; boolean busy = Store.busy.get(), wifi = WifiLink.connected();
        JSONObject pack = Store.json(this, "package.json"), instrument = Store.json(this, "instrument.json");
        String key = busy + "|" + wifi + "|" + Store.phase + "|" + Store.message + "|" + Store.percent + "|" + pack + "|" + instrument; if (key.equals(last)) return; last = key;
        packageText.setText(pack.has("sha256") ? (pack.optString("kind").equals("incremental") ? "文件增量" : "全量固件") + " · " + (pack.optBoolean("signed") ? "签名已校验" : "原厂 SHA-256 已核对")
                + "\n" + pack.optString("release") + "\n" + String.format(Locale.ROOT, "%.2f MiB", pack.optLong("bytes") / 1048576.0)
                + (pack.optString("base_version").isEmpty() ? "" : "\n适用版本：" + pack.optString("base_version")) : "选择原厂全量 TAR，或带签名、测试及回退脚本的增量 TAR。");
        wifiText.setText(wifi ? "Wi-Fi 已选择 · 更新流量固定走此网络" : "请连接仪表热点");
        versionText.setText(instrument.has("version") ? "上次读取：" + instrument.optString("version") + "\n开始 OTA 时会重新读取并核对。" : "开始 OTA 时读取并核对仪表型号、版本。");
        stateText.setText(Store.message); bar.setProgress(Store.percent);
        enable(choose, !busy); enable(scan, !busy); enable(join, !busy); enable(adopt, !busy); enable(read, !busy && wifi);
        enable(start, !busy && wifi && pack.has("sha256")); enable(stop, busy && !Store.phase.equals("INSTALL_REQUESTED"));
    }
    private void confirm(boolean update) {
        JSONObject pack = Store.json(this, "package.json");
        new AlertDialog.Builder(this).setTitle(update ? "开始仪表 OTA？" : "连接仪表读取版本？")
                .setMessage("连接升级端口会停止 DVR 和部分投屏进程，请停车并保持稳定供电。" + (update ? "\n\n" + (pack.optString("kind").equals("incremental") ? "本次为文件增量，安装后由包内脚本验证，失败或超时回退。" : "本次为全量更新，可能包含引导、内核、MCU 和数据清理。")
                        + "\n\n文件接收后将立即发送安装确认。最终安装结果需在仪表确认。" : "\n\n本次只读取型号和版本。"))
                .setNegativeButton("取消", null).setPositiveButton(update ? "开始 OTA" : "读取版本", (d, w) -> permissions(() -> action(update ? UpdateService.UPDATE : UpdateService.VERSION, null))).show();
    }
    private void action(String action, Uri uri) {
        if (Store.busy.get()) return;
        try {
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 20);
            Intent i = new Intent(this, UpdateService.class).setAction(action); if (uri != null) i.setData(uri); startForegroundService(i);
        } catch (Exception e) { error(e); }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null) return;
        if (request == SCAN_WIFI) {
            if (!Store.busy.get()) confirmScannedWifi(data.getStringExtra(InstrumentQRScanner.EXTRA_CODE));
            return;
        }
        if (data.getData() == null) return;
        if (request == PICK) action(UpdateService.IMPORT, data.getData());
        if (request == EXPORT) try (OutputStream out = getContentResolver().openOutputStream(data.getData())) {
            if (out == null) throw new IOException("无法创建日志"); File file = Store.file(this, "events.log"); out.write(file.exists() ? Store.bytes(file, 131072) : "尚无日志\n".getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) { error(e); }
    }
    private void permissions(Runnable next) {
        ArrayList<String> missing = new ArrayList<>(); String nearby = Build.VERSION.SDK_INT >= 33 ? "android.permission.NEARBY_WIFI_DEVICES" : Manifest.permission.ACCESS_FINE_LOCATION;
        if (checkSelfPermission(nearby) != PackageManager.PERMISSION_GRANTED) missing.add(nearby);
        if (Build.VERSION.SDK_INT >= 37 && checkSelfPermission("android.permission.ACCESS_LOCAL_NETWORK") != PackageManager.PERMISSION_GRANTED) missing.add("android.permission.ACCESS_LOCAL_NETWORK");
        if (missing.isEmpty()) next.run(); else { pendingWifi = next; requestPermissions(missing.toArray(new String[0]), PERMISSIONS); }
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == PERMISSIONS) {
            boolean ok = results.length > 0; for (int value : results) ok &= value == PackageManager.PERMISSION_GRANTED;
            if (ok && pendingWifi != null) pendingWifi.run(); else Toast.makeText(this, "连接仪表需要对应系统版本的附近设备、局域网权限", Toast.LENGTH_LONG).show(); pendingWifi = null;
        }
    }
    private void scanWifi() {
        if (Store.busy.get()) return;
        startActivityForResult(new Intent(this, InstrumentQRScanner.class), SCAN_WIFI);
    }
    private void confirmScannedWifi(String rawCode) {
        final InstrumentWifiCode code;
        try { code = InstrumentWifiCode.parse(rawCode); }
        catch (IllegalArgumentException invalid) { error(invalid); return; }
        new AlertDialog.Builder(this).setTitle("连接扫描到的热点")
                .setMessage(code.ssid)
                .setNegativeButton("取消", null)
                .setPositiveButton("连接", (dialog, button) -> permissions(() -> {
                    if (Store.busy.get()) return;
                    try { WifiLink.request(this, code.ssid, code.password); }
                    catch (RuntimeException failed) { error(new IOException("无法请求连接，请检查 Wi-Fi 和局域网权限。")); }
                })).show();
    }
    private void wifiDialog() {
        LinearLayout form = column(); form.setPadding(dp(24), dp(8), dp(24), 0);
        EditText ssid = new EditText(this); ssid.setHint("仪表热点名称"); ssid.setSingleLine(); form.addView(ssid);
        EditText password = new EditText(this); password.setHint("热点密码（开放热点留空）"); password.setSingleLine(); password.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); password.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO); form.addView(password);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("连接仪表热点").setView(form).setNegativeButton("取消", null)
                .setNeutralButton("Wi-Fi 设置", (d, w) -> startActivity(new Intent(Settings.Panel.ACTION_WIFI))).setPositiveButton("连接", null).create();
        dialog.setOnShowListener(v -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(b -> {
            try { String name = ssid.getText().toString().trim(); if (name.isEmpty()) throw new IOException("请输入热点名称"); WifiLink.request(this, name, password.getText().toString()); dialog.dismiss(); }
            catch (Exception e) { Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show(); }
        })); dialog.show();
    }
    private void error(Exception e) { new AlertDialog.Builder(this).setTitle("操作未完成").setMessage(e.getMessage()).setPositiveButton("知道了", null).show(); }
}
