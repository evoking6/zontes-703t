package cn.local.instrument703t;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.database.Cursor;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.util.AtomicFile;
import cn.local.instrument703t.core.*;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

public final class UpdateService extends Service {
    static final String IMPORT = "IMPORT", UPDATE = "UPDATE", VERSION = "VERSION";
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private PowerManager.WakeLock wakeLock;
    private static volatile Socket activeSocket;
    private volatile boolean installAttempted;
    private long lastProgress;
    static void cancelTransfer() {
        if (Store.phase.equals("INSTALL_REQUESTED")) return;
        Store.cancel = true; Socket s = activeSocket; if (s != null) try { s.close(); } catch (IOException ignored) { }
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) { stopSelf(); return START_NOT_STICKY; }
        if (!Store.busy.compareAndSet(false, true)) return START_NOT_STICKY;
        Store.cancel = false; installAttempted = false; String action = intent.getAction(); Uri uri = intent.getData();
        try {
            getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel("ota", "仪表 OTA", NotificationManager.IMPORTANCE_LOW));
            startForeground(703, notification("正在处理"), IMPORT.equals(action) ? ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC : ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
            wakeLock = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "703t:ota"); wakeLock.acquire(45 * 60 * 1000L);
        } catch (Exception e) { Store.busy.set(false); Store.status(this, "ERROR", clean(e), 0); stopSelf(); return START_NOT_STICKY; }
        worker.execute(() -> {
            try {
                if (IMPORT.equals(action)) importPackage(uri);
                else if (UPDATE.equals(action) || VERSION.equals(action)) connect(UPDATE.equals(action));
                else throw new IOException("未知操作");
            } catch (Exception e) {
                Store.status(this, installAttempted ? "INSTALL_REQUESTED" : Store.cancel ? "CANCELLED" : "ERROR",
                        installAttempted ? "已尝试发送安装确认，连接结果不确定。请检查仪表，不要直接重复升级。" : clean(e), Store.percent); log(Store.message);
            } finally {
                Socket s = activeSocket; activeSocket = null; if (s != null) try { s.close(); } catch (IOException ignored) { }
                if (wakeLock != null && wakeLock.isHeld()) wakeLock.release(); Store.busy.set(false); stopForeground(STOP_FOREGROUND_REMOVE); stopSelf();
            }
        }); return START_NOT_STICKY;
    }
    @Override public void onTimeout(int startId, int type) { cancelTransfer(); stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); }
    @Override public void onDestroy() { worker.shutdown(); super.onDestroy(); }
    private Notification notification(String value) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, "ota").setSmallIcon(R.drawable.ic_launcher).setContentTitle("703T 仪表 OTA").setContentText(value).setContentIntent(open).setOnlyAlertOnce(true).setOngoing(true).build();
    }
    private String clean(Exception e) {
        if (e instanceof ConnectException || e instanceof SocketTimeoutException) return "仪表未响应，请检查热点和升级状态。不会自动重试或发送安装确认。";
        String value = e.getMessage(); return value == null ? "操作未完成，请检查文件与仪表状态。" : value.substring(0, Math.min(240, value.length()));
    }
    private synchronized void progress(String phase, String text, long at, long total) throws IOException {
        Store.checkCancelled(); long now = SystemClock.elapsedRealtime(); if (now - lastProgress < 300 && at < total) return; lastProgress = now;
        int p = total > 0 ? (int) Math.min(100, at * 100 / total) : 0; Store.status(this, phase, text, p);
        getSystemService(NotificationManager.class).notify(703, notification(text));
    }
    private void importPackage(Uri uri) throws Exception {
        NativePackage.need(uri != null, "请选择固件 TAR"); Store.file(this, "package.json").delete(); String name = "本地固件.tar";
        try (Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) { if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0); }
        Store.status(this, "IMPORTING", "正在缓存所选固件", 0);
        AtomicFile cache = new AtomicFile(Store.file(this, "firmware.tar")); FileOutputStream stream = null;
        try (InputStream in = getContentResolver().openInputStream(uri)) {
            NativePackage.need(in != null, "无法打开所选文件"); stream = cache.startWrite(); byte[] buffer = new byte[65536]; int n; long size = 0;
            while ((n = in.read(buffer)) != -1) {
                Store.checkCancelled(); size += n; NativePackage.need(size <= NativePackage.MAX_BYTES, "固件超过 520 MiB 上限");
                NativePackage.need(getFilesDir().getUsableSpace() > 32L * 1024 * 1024, "手机空间不足，请保留至少 32 MiB 余量");
                stream.write(buffer, 0, n); progress("IMPORTING", "缓存固件：" + size / 1048576 + " MiB", 0, 1);
            }
            cache.finishWrite(stream); stream = null;
        } catch (Exception e) { if (stream != null) cache.failWrite(stream); throw e; }
        NativePackage.Result pack = verify();
        Store.json(this, "package.json", new JSONObject().put("name", name).put("kind", pack.kind).put("release", pack.release).put("base_version", pack.baseVersion)
                .put("sha256", pack.sha256).put("bytes", pack.bytes).put("files", pack.files).put("signed", pack.signed));
        Store.status(this, "READY", pack.signed ? "签名及所有文件校验通过，尚未传输。" : "与已分析的原厂全量包 SHA-256 完全一致，尚未传输。", 0);
        log("选包通过：" + pack.kind + " " + pack.release + " " + pack.sha256);
    }
    private NativePackage.Result verify() throws Exception {
        Store.status(this, "VERIFYING", "正在校验固件", 0);
        return NativePackage.verify(Store.file(this, "firmware.tar"), BundledTrust.key(this), (at, total) -> progress("VERIFYING", "校验签名和文件完整性", at, total));
    }
    private void connect(boolean update) throws Exception {
        NativePackage.Result pack = null;
        if (update) {
            NativePackage.need(Store.json(this, "package.json").has("sha256"), "请先选择有效固件"); pack = verify();
            NativePackage.need(pack.sha256.equals(Store.json(this, "package.json").optString("sha256")), "固件缓存变化，请重新选包");
        }
        Store.checkCancelled(); android.net.Network network = WifiLink.get(); Store.status(this, "CHECKING", "连接仪表并读取型号、版本", 0);
        Socket socket = network.getSocketFactory().createSocket(); activeSocket = socket; socket.connect(new InetSocketAddress("192.168.3.1", NativeOtaClient.PORT), 8000);
        final NativePackage.Result selected = pack;
        try (NativeOtaClient client = new NativeOtaClient(socket, new NativeOtaClient.Listener() {
            public void checkCancelled() throws IOException { Store.checkCancelled(); }
            public void version(String version) throws IOException {
                try { Store.json(UpdateService.this, "instrument.json", new JSONObject().put("version", version).put("read_at", System.currentTimeMillis())); }
                catch (Exception e) { throw new IOException("无法保存仪表版本", e); } log("仪表报告版本：" + version);
            }
            public void progress(long sent, long total, int received) throws IOException {
                UpdateService.this.progress("UPLOADING", "手机已发送 " + sent / 1024 + " KiB；仪表接收 " + received + "%", sent, total);
            }
            public void beforeInstall() throws IOException {
                Store.checkCancelled();
                try { Store.json(UpdateService.this, "last-update.json", new JSONObject().put("sha256", selected.sha256).put("release", selected.release)
                            .put("kind", selected.kind).put("state", "INSTALL_REQUESTED").put("time", System.currentTimeMillis())); }
                catch (Exception e) { throw new IOException("无法保存操作记录，不会发送安装确认", e); }
                installAttempted = true; Store.status(UpdateService.this, "INSTALL_REQUESTED", "文件接收完成，正在发送最后安装确认", 100);
            }
        })) {
            if (update) {
                client.update(Store.file(this, "firmware.tar"), pack);
                Store.status(this, "INSTALL_REQUESTED", "仪表已接收文件，安装确认已发送。请查看仪表完成安装、测试或回退；本工具无法读取最终结果。", 100); log("安装确认已发送，最终结果待实机确认");
            } else { String version = client.queryVersion(); Store.status(this, "VERSION", "仪表报告：" + version + "。本次只读取版本。", 0); }
        } finally { activeSocket = null; }
    }
    private void log(String text) {
        try { File file = Store.file(this, "events.log"); if (file.length() > 65536) file.delete();
            try (FileOutputStream out = new FileOutputStream(file, true)) { out.write((new java.util.Date() + "  " + text + "\n").getBytes(StandardCharsets.UTF_8)); }
        } catch (IOException ignored) { }
    }
}
