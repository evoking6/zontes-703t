package cn.local.instrument703t;

import android.content.Context;
import android.net.*;
import android.net.wifi.WifiNetworkSpecifier;
import java.io.IOException;

final class WifiLink {
    private static volatile Network network;
    private static ConnectivityManager manager;
    private static ConnectivityManager.NetworkCallback callback;
    static Network get() throws IOException {
        if (!connected()) throw new IOException("请先连接仪表 Wi-Fi；不会通过移动数据发送固件");
        return network;
    }
    static boolean connected() {
        Network n = network;
        if (n == null || manager == null) return false;
        NetworkCapabilities caps = manager.getNetworkCapabilities(n);
        return caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
    }
    static synchronized void request(Context context, String ssid, String password) {
        Context c = context.getApplicationContext(); release(c);
        WifiNetworkSpecifier.Builder spec = new WifiNetworkSpecifier.Builder().setSsid(ssid);
        if (!password.isEmpty()) spec.setWpa2Passphrase(password);
        ConnectivityManager cm = (ConnectivityManager) c.getSystemService(Context.CONNECTIVITY_SERVICE);
        manager = cm;
        NetworkRequest request = new NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).setNetworkSpecifier(spec.build()).build();
        callback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network n) {
                synchronized (WifiLink.class) {
                    if (callback != this) return;
                    network = n;
                    Store.status(c, "WIFI", "已连接仪表 Wi-Fi，可以读取版本或开始 OTA。", 0);
                }
            }
            @Override public void onLost(Network n) {
                synchronized (WifiLink.class) {
                    if (callback != this || !n.equals(network)) return;
                    network = null;
                    if (!Store.busy.get() && !Store.phase.equals("INSTALL_REQUESTED")) Store.status(c, "DISCONNECTED", "仪表 Wi-Fi 已断开，请检查仪表状态后再操作。", Store.percent);
                }
            }
            @Override public void onUnavailable() {
                synchronized (WifiLink.class) {
                    if (callback != this) return;
                    callback = null;
                    network = null;
                    Store.status(c, "DISCONNECTED", "未能连接 Wi-Fi，请确认热点名称、密码与系统权限。", 0);
                }
            }
        };
        cm.requestNetwork(request, callback, 45000);
        Store.status(c, "CONNECTING", "请在系统弹窗中确认连接仪表热点。", 0);
    }
    static synchronized void adopt(Context c) throws IOException {
        ConnectivityManager cm = (ConnectivityManager) c.getSystemService(Context.CONNECTIVITY_SERVICE);
        manager = cm;
        for (Network n : cm.getAllNetworks()) {
            NetworkCapabilities caps = cm.getNetworkCapabilities(n);
            if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                network = n; Store.status(c, "WIFI", "已选择当前 Wi-Fi，请确认这是仪表热点。", 0); return;
            }
        }
        throw new IOException("当前没有可用的 Wi-Fi，请先在系统设置连接仪表热点");
    }
    static synchronized void release(Context c) {
        if (callback != null) {
            try { ((ConnectivityManager) c.getSystemService(Context.CONNECTIVITY_SERVICE)).unregisterNetworkCallback(callback); }
            catch (Exception ignored) { }
        }
        callback = null; network = null;
    }
}
