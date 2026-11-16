package cn.local.instrument703t;

import com.google.zxing.qrcode.QRCodeReader;
import com.google.zxing.qrcode.QRCodeWriter;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.common.BitMatrix;

/** Exercises the scanner's image-to-credentials path with synthetic, non-secret QR codes. */
public final class InstrumentWifiCodeChecks {
    public static void main(String[] args) throws Exception {
        String escaped = "WIFI:T:WPA;S:JC\\;703T;P:ab\\:cd\\;12;;";
        BitMatrix image = new QRCodeWriter().encode(escaped, BarcodeFormat.QR_CODE, 320, 320);
        int width = image.getWidth();
        for (int rotation = 0; rotation < 4; rotation++) {
            byte[] luminance = new byte[width * width];
            for (int y = 0; y < width; y++) {
                for (int x = 0; x < width; x++) {
                    int fromX = x, fromY = y;
                    for (int turn = 0; turn < rotation; turn++) {
                        int oldX = fromX;
                        fromX = fromY;
                        fromY = width - oldX - 1;
                    }
                    luminance[y * width + x] = (byte) (image.get(fromX, fromY) ? 0 : 255);
                }
            }
            String text = InstrumentQRScanner.decode(new QRCodeReader(), luminance, width, width);
            InstrumentWifiCode result = InstrumentWifiCode.parse(text);
            if (!result.ssid.equals("JC;703T") || !result.password.equals("ab:cd;12")) {
                throw new AssertionError("Rotated Wi-Fi QR lost escaped characters");
            }
        }
        if (!InstrumentWifiCode.parse("WIFI:T:nopass;S:Fixture;;").password.isEmpty()) {
            throw new AssertionError("Open network requires no password");
        }
        String projection = "http://www.carbit.com.cn/downsdk/697/698/_sdk?modelid=0&ssid=JC%20Fixture"
                + "&pwd=ab%2Bcd%26ef&auth=WPA2&machinetype=JC_703T25_V00.00.00.00.00";
        InstrumentWifiCode stock = InstrumentWifiCode.parse(projection);
        if (!stock.ssid.equals("JC Fixture") || !stock.password.equals("ab+cd&ef")) {
            throw new AssertionError("Stock projection QR lost URL encoding");
        }
        for (String invalid : new String[]{"https://example.com", "WIFI:T:WPA;P:abcdefgh;;",
                "WIFI:T:WPA;S:Fixture;S:Other;P:abcdefgh;;", "WIFI:T:WPA;S:Fixture;P:short;;",
                "WIFI:T:WPA;S:Fixture;P:abcdefgh\\", "WIFI:T:WPA;S:Fixture;P:abcdefgh;H:true;;",
                "WIFI:T:WEP;S:Fixture;P:abcdefgh;;", projection + "&sSiD=Duplicate",
                projection.replace("www.carbit.com.cn", "example.com"), projection.replace("JC_703T25", "OTHER")}) {
            try {
                InstrumentWifiCode.parse(invalid);
                throw new AssertionError("Invalid Wi-Fi QR accepted");
            } catch (IllegalArgumentException expected) { }
        }
        System.out.println("PASS four image rotations, Wi-Fi and stock projection QR credentials, open network, and invalid input rejection");
    }
}
