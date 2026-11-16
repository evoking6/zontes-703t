package cn.local.instrument703t.core;

import java.io.*;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.regex.*;

/** Stock mode-0 TCP protocol, reconstructed from Launcher. No HTTP, shell or resume. */
public final class NativeOtaClient implements Closeable {
    public interface Listener {
        void checkCancelled() throws IOException;
        void version(String version) throws IOException;
        void progress(long sent, long total, int receivedPercent) throws IOException;
        void beforeInstall() throws IOException;
    }
    public static final int PORT = 8081, BLOCK = 4096;
    private final Socket socket;
    private final InputStream in;
    private final OutputStream out;
    private final Listener listener;
    private volatile IOException failure;
    private volatile boolean received;
    private volatile int percent;
    private volatile long sent;
    private Thread reader;
    public NativeOtaClient(Socket socket, Listener listener) throws IOException {
        this.socket = socket; this.listener = listener;
        socket.setSoTimeout(15000); socket.setTcpNoDelay(true);
        in = socket.getInputStream(); out = socket.getOutputStream();
    }
    public static byte[] frame(int type, byte[] payload) throws IOException {
        int length = payload.length + 1; NativePackage.need(length <= 65535, "报文过长");
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(length + 4);
        bytes.write(length >> 8); bytes.write(length); bytes.write(type); bytes.write(payload); bytes.write('J'); bytes.write('C'); return bytes.toByteArray();
    }
    private byte[] readFrame() throws IOException {
        listener.checkCancelled(); int hi = in.read(), lo = in.read();
        if (hi < 0 || lo < 0) throw new EOFException("仪表连接已断开");
        int length = (hi << 8) | lo; NativePackage.need(length >= 1 && length <= 4096, "仪表响应长度错误");
        byte[] body = new byte[length]; new DataInputStream(in).readFully(body);
        NativePackage.need(in.read() == 'J' && in.read() == 'C', "仪表响应尾标记错误"); return body;
    }
    public String queryVersion() throws IOException {
        out.write(frame(0, new byte[0])); out.flush(); byte[] body = readFrame();
        NativePackage.need(body.length == 67 && body[0] == 1 && body[1] == 'J' && body[2] == 'C', "不是已识别的仪表升级协议");
        Matcher matcher = Pattern.compile("JC_703T25_V[0-9]+(?:\\.[0-9]+){4}").matcher(new String(body, StandardCharsets.US_ASCII));
        NativePackage.need(matcher.find(), "仪表型号或版本响应不匹配"); String version = matcher.group(); listener.version(version); return version;
    }
    public void update(File file, NativePackage.Result pack) throws Exception {
        pack.checkVersion(queryVersion());
        NativePackage.need(file.length() == pack.bytes, "缓存固件长度已变化");
        byte[] name = pack.wireName.getBytes(StandardCharsets.US_ASCII); NativePackage.need(name.length <= 32, "升级文件名过长");
        ByteArrayOutputStream meta = new ByteArrayOutputStream(); DataOutputStream data = new DataOutputStream(meta);
        data.writeInt((int) pack.bytes); data.writeShort(name.length); data.write(Arrays.copyOf(name, 32));
        out.write(frame(2, meta.toByteArray())); out.flush(); byte[] reply = readFrame();
        NativePackage.need(reply.length == 3 && reply[0] == 2, "仪表文件信息响应错误");
        NativePackage.need((reply[1] & 255) == 0 && (reply[2] & 255) == 200, "仪表拒绝接收此固件");
        reader = new Thread(() -> {
            try {
                while (!received) {
                    byte[] body = readFrame(); int type = body[0] & 255;
                    if (type == 6 && body.length == 2) {
                        int next = body[1] & 255; NativePackage.need(next <= 100 && next >= percent, "仪表进度响应错误"); percent = next;
                        listener.progress(sent, pack.bytes, percent);
                    } else if (type == 4 && body.length == 1) received = true;
                    else if (type == 3 && body.length == 6) NativePackage.need(body[1] == 0 && (body[2] & 255) == 200, "仪表报告分包失败");
                    else throw new IOException("仪表返回不支持的升级响应");
                }
            } catch (IOException e) { failure = e; try { socket.close(); } catch (IOException ignored) { } }
        }, "stock-ota-replies"); reader.setDaemon(true); reader.start();
        try (InputStream firmware = new FileInputStream(file)) {
            byte[] chunk = new byte[BLOCK]; int sequence = 0; long remaining = pack.bytes;
            while (remaining > 0) {
                check(); NativePackage.need(!received, "仪表提前结束接收，未请求安装");
                // The receiver reports whole percentages, not per-block ACKs. Keep queued
                // payload below its 16 MiB FIFO while allowing the next 1% to arrive.
                long window = Math.max(256 * 1024L, (pack.bytes + 99) / 100 + 65536);
                while (sent - percent * pack.bytes / 100 >= window) {
                    check(); NativePackage.need(!received, "仪表提前结束接收，未请求安装"); Thread.sleep(10);
                }
                int count = (int) Math.min(remaining, BLOCK); new DataInputStream(firmware).readFully(chunk, 0, count);
                ByteArrayOutputStream block = new ByteArrayOutputStream(count + 4);
                block.write(remaining == count ? 1 : 0); block.write(sequence >> 16); block.write(sequence >> 8); block.write(sequence); block.write(chunk, 0, count);
                out.write(frame(3, block.toByteArray())); out.flush(); sent += count; remaining -= count; sequence++;
                listener.progress(sent, pack.bytes, percent);
                // Bound the stock receiver's FIFO/debug workload; there is no per-block ACK contract.
                Thread.sleep(2);
            }
        }
        long deadline = System.nanoTime() + 20_000_000_000L;
        while (!received) { check(); NativePackage.need(System.nanoTime() < deadline, "未收到仪表接收结束确认，不会发送安装指令"); Thread.sleep(20); }
        check(); NativePackage.need(sent == pack.bytes, "文件未传完整，不会请求安装");
        // Persist uncertainty before sending: a disconnect after this write is not proof of failure or success.
        listener.beforeInstall(); out.write(frame(5, new byte[0])); out.flush();
        // The factory parser changes state and aborts its socket after consuming
        // type 5. Closing from our side first can run on_disconnected and reset
        // that state before the confirmation is processed. Let the receiver end
        // the session; this still does not establish installation success.
        if (reader != null) reader.join(1000);
        long closeDeadline = System.nanoTime() + 5_000_000_000L;
        int trailing = 0;
        try {
            while (true) {
                long remaining = (closeDeadline - System.nanoTime()) / 1_000_000L;
                NativePackage.need(remaining > 0 && trailing < 4096, "安装确认已发送，仪表未结束传输会话，安装状态不确定");
                socket.setSoTimeout((int) Math.max(1, remaining));
                if (in.read() < 0) break;
                trailing++;
            }
        } catch (java.net.SocketException disconnected) {
            // QAbstractSocket::abort can end with FIN or RST depending on queued data.
        }
    }
    private void check() throws IOException { listener.checkCancelled(); if (failure != null) throw failure; }
    @Override public void close() throws IOException {
        socket.close();
        if (reader != null) { try { reader.join(1000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); } }
    }
}
