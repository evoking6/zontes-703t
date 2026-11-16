package cn.local.instrument703t;
import android.content.Context;
import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;

final class Store {
    static final AtomicBoolean busy = new AtomicBoolean();
    static volatile boolean cancel;
    static volatile int percent;
    static volatile String phase = "IDLE", message = "选择全量或增量 TAR，连接仪表热点后开始 OTA。";
    static File file(Context c, String name) { return new File(c.getFilesDir(), name); }
    static byte[] bytes(File file, int max) throws IOException { try (InputStream in = new AtomicFile(file).openRead()) { return bytes(in, max); } }
    static byte[] bytes(InputStream in, int max) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int n;
        while ((n = in.read(buffer)) != -1) { if (out.size() + n > max) throw new IOException("文件过大"); out.write(buffer, 0, n); } return out.toByteArray();
    }
    static void write(File file, byte[] data) throws IOException {
        AtomicFile atomic = new AtomicFile(file); FileOutputStream stream = null;
        try { stream = atomic.startWrite(); stream.write(data); atomic.finishWrite(stream); }
        catch (IOException e) { if (stream != null) atomic.failWrite(stream); throw e; }
    }
    static JSONObject json(Context c, String name) {
        try { return new JSONObject(new String(bytes(file(c, name), 1024 * 1024), StandardCharsets.UTF_8)); } catch (Exception e) { return new JSONObject(); }
    }
    static void json(Context c, String name, JSONObject value) throws IOException { write(file(c, name), value.toString().getBytes(StandardCharsets.UTF_8)); }
    static synchronized void status(Context c, String stage, String text, int progress) {
        phase = stage; message = text; percent = Math.max(0, Math.min(100, progress));
        c.getSharedPreferences("status", 0).edit().putString("phase", stage).putString("message", text).putInt("percent", percent).apply();
    }
    static void restore(Context c) {
        if (busy.get()) return;
        phase = c.getSharedPreferences("status", 0).getString("phase", "IDLE"); message = c.getSharedPreferences("status", 0).getString("message", message);
        percent = c.getSharedPreferences("status", 0).getInt("percent", 0);
        if (json(c, "last-update.json").optString("state").equals("INSTALL_REQUESTED")) phase = "INSTALL_REQUESTED";
        if (phase.equals("UPLOADING") || phase.equals("CHECKING") || phase.equals("IMPORTING") || phase.equals("VERIFYING"))
            status(c, "INTERRUPTED", "上次操作已中断。原厂协议不支持可靠续传，确认仪表状态后再重新开始。", percent);
        if (phase.equals("INSTALL_REQUESTED")) message = "已尝试发送安装确认，最终结果未知。请先检查仪表，避免重复升级。";
    }
    static void checkCancelled() throws IOException { if (cancel || Thread.currentThread().isInterrupted()) throw new IOException("已停止手机传输；请检查仪表状态后重新开始"); }
}
