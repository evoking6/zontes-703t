package cn.local.instrument703t;

import java.io.UnsupportedEncodingException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

final class InstrumentWifiCode {
    final String ssid;
    final String password;

    private InstrumentWifiCode(String ssid, String password) {
        this.ssid = ssid;
        this.password = password;
    }

    static InstrumentWifiCode parse(String raw) {
        if (raw == null || raw.getBytes(StandardCharsets.UTF_8).length > 1024) {
            throw new IllegalArgumentException("请扫描仪表投屏页面上的 Wi-Fi 二维码。");
        }
        if (!raw.startsWith("WIFI:")) return parseProjectionLink(raw);
        Map<String, String> fields = new HashMap<>();
        StringBuilder field = new StringBuilder();
        for (int i = 5; i < raw.length(); i++) {
            char character = raw.charAt(i);
            if (character == '\\') {
                if (++i == raw.length()) throw invalid();
                field.append(raw.charAt(i));
            } else if (character == ';') {
                addField(fields, field);
                field.setLength(0);
            } else {
                field.append(character);
            }
        }
        addField(fields, field);

        String hidden = fields.get("H");
        if (hidden != null && !hidden.isEmpty() && !hidden.equalsIgnoreCase("false")) {
            throw new IllegalArgumentException("请在系统 Wi-Fi 设置中连接隐藏热点。");
        }
        return credentials(fields.getOrDefault("S", ""), fields.getOrDefault("P", ""), fields.getOrDefault("T", ""));
    }

    private static InstrumentWifiCode parseProjectionLink(String raw) {
        Map<String, String> fields = new HashMap<>();
        try {
            // The stock display wraps Wi-Fi credentials in this Carbit projection link.
            // Interpret the query locally. The URL is never opened.
            URI uri = new URI(raw);
            if (!("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme()))
                    || !"www.carbit.com.cn".equalsIgnoreCase(uri.getHost())
                    || uri.getPort() != -1 || uri.getRawUserInfo() != null || uri.getRawFragment() != null
                    || !uri.getRawPath().matches("/downsdk/[0-9]+/[0-9]+/_sdk") || uri.getRawQuery() == null) {
                throw invalid();
            }
            for (String parameter : uri.getRawQuery().split("&")) {
                int equals = parameter.indexOf('=');
                if (equals < 1) throw invalid();
                String key = URLDecoder.decode(parameter.substring(0, equals), "UTF-8").toLowerCase(Locale.ROOT);
                String value = URLDecoder.decode(parameter.substring(equals + 1), "UTF-8");
                if (fields.putIfAbsent(key, value) != null) throw invalid();
            }
            if (!fields.getOrDefault("machinetype", "").matches("JC_703T25_V[0-9]+(?:\\.[0-9]+)+")) {
                throw invalid();
            }
        } catch (URISyntaxException | UnsupportedEncodingException | IllegalArgumentException malformed) {
            throw new IllegalArgumentException("请扫描 703T 仪表投屏页面上的 Wi-Fi 二维码。");
        }
        return credentials(fields.getOrDefault("ssid", ""), fields.getOrDefault("pwd", ""), fields.getOrDefault("auth", ""));
    }

    private static InstrumentWifiCode credentials(String ssid, String password, String security) {
        if (ssid.isEmpty() || ssid.getBytes(StandardCharsets.UTF_8).length > 32
                || ssid.chars().anyMatch(Character::isISOControl)) {
            throw new IllegalArgumentException("二维码中的热点名称无效。");
        }
        switch (security.toUpperCase(Locale.ROOT)) {
            case "WPA":
            case "WPA2":
            case "WPA2-PSK":
                if (password.length() < 8 || password.length() > 63
                        || password.chars().anyMatch(value -> value < 32 || value > 126)) {
                    throw new IllegalArgumentException("二维码中的 WPA2 密码无效。");
                }
                break;
            case "NOPASS":
                if (!password.isEmpty()) throw invalid();
                break;
            default:
                throw new IllegalArgumentException("请扫描 WPA2 或开放热点的 Wi-Fi 二维码。");
        }
        return new InstrumentWifiCode(ssid, password);
    }

    private static void addField(Map<String, String> fields, StringBuilder field) {
        if (field.length() == 0) return;
        int separator = field.indexOf(":");
        if (separator <= 0 || fields.putIfAbsent(field.substring(0, separator), field.substring(separator + 1)) != null) {
            throw invalid();
        }
    }

    private static IllegalArgumentException invalid() {
        return new IllegalArgumentException("仪表 Wi-Fi 二维码格式无效。");
    }
}
