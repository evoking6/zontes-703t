package cn.local.instrument703t;

import android.content.Context;
import cn.local.instrument703t.core.NativePackage;
import java.io.InputStream;

/** The signed APK's public asset is the sole release trust root. */
final class BundledTrust {
    private static byte[] cached;

    static synchronized byte[] key(Context context) throws Exception {
        if (cached == null) {
            byte[] bytes;
            try (InputStream in = context.getAssets().open("release-public.pem")) { bytes = Store.bytes(in, 8192); }
            NativePackage.publicKey(bytes);
            cached = bytes;
        }
        return cached.clone();
    }

    static String initialize(Context context) throws Exception {
        String id = NativePackage.keyId(key(context));
        if (!context.getSharedPreferences("trust", 0).getBoolean("native_v1", false)) {
            Store.file(context, "verified.json").delete();
            Store.status(context, "IDLE", "选择全量或增量 TAR，连接仪表热点后开始 OTA。", 0);
            context.getSharedPreferences("trust", 0).edit().putBoolean("native_v1", true).apply();
        }
        // Version 0.1.0 allowed an imported public key. Never use that cache as a trust root.
        Store.file(context, "release-public.pem").delete();
        for (String name : new String[]{"device-profile.enc", "device.json", "session.json", "firmware.703t-ota"}) Store.file(context, name).delete();
        String previous = context.getSharedPreferences("trust", 0).getString("bundled_key_id", "");
        if (!id.equals(previous)) {
            Store.file(context, "device.json").delete();
            context.getSharedPreferences("trust", 0).edit().putString("bundled_key_id", id).apply();
            Store.status(context, "KEY_READY", "发布公钥已内置，请直接选择本地固件。", 0);
        }
        return id;
    }
}
