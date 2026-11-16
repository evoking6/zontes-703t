package cn.local.instrument703t.core;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Small strict parser shared by the Android client and host-side contract tests. */
public final class StrictJson {
    private final String text;
    private int position;
    private StrictJson(String value) { text = value; }

    public static Object parse(String text) throws IOException {
        StrictJson p = new StrictJson(text);
        Object value = p.value(0);
        p.space();
        p.need(p.position == text.length(), "JSON 含多余内容");
        return value;
    }

    private void need(boolean condition, String message) throws IOException {
        if (!condition) throw new IOException(message);
    }

    private void space() {
        while (position < text.length() && " \t\r\n".indexOf(text.charAt(position)) >= 0) position++;
    }

    private char next() throws IOException {
        need(position < text.length(), "JSON 意外结束");
        return text.charAt(position++);
    }

    private Object value(int depth) throws IOException {
        need(depth <= 32, "JSON 嵌套过深");
        space();
        need(position < text.length(), "JSON 内容缺失");
        char c = text.charAt(position);
        if (c == '"') return string();
        if (c == '{') {
            position++;
            Map<String, Object> map = new LinkedHashMap<>();
            space();
            if (position < text.length() && text.charAt(position) == '}') { position++; return map; }
            while (true) {
                space();
                String key = string();
                need(!map.containsKey(key), "JSON 键重复: " + key);
                space(); need(next() == ':', "JSON 缺少冒号");
                map.put(key, value(depth + 1));
                need(map.size() <= 8192, "JSON 对象过大");
                space(); c = next();
                if (c == '}') return map;
                need(c == ',', "JSON 对象分隔错误");
            }
        }
        if (c == '[') {
            position++;
            List<Object> list = new ArrayList<>();
            space();
            if (position < text.length() && text.charAt(position) == ']') { position++; return list; }
            while (true) {
                list.add(value(depth + 1));
                need(list.size() <= 8192, "JSON 数组过大");
                space(); c = next();
                if (c == ']') return list;
                need(c == ',', "JSON 数组分隔错误");
            }
        }
        for (String word : new String[]{"true", "false", "null"}) {
            if (text.startsWith(word, position)) {
                position += word.length();
                return word.equals("null") ? null : Boolean.valueOf(word);
            }
        }
        int start = position;
        if (c == '-') position++;
        need(position < text.length(), "JSON 数字错误");
        if (text.charAt(position) == '0') position++;
        else {
            need(text.charAt(position) >= '1' && text.charAt(position) <= '9', "JSON 值错误");
            while (position < text.length() && text.charAt(position) >= '0' && text.charAt(position) <= '9') position++;
        }
        // The v1 contract only uses integers. No lossy float conversions.
        need(position == text.length() || ".eE".indexOf(text.charAt(position)) < 0, "协议 v1 不接受小数");
        try { return Long.valueOf(text.substring(start, position)); }
        catch (NumberFormatException error) { throw new IOException("JSON 整数溢出", error); }
    }

    private String string() throws IOException {
        need(next() == '"', "JSON 键或字符串错误");
        StringBuilder out = new StringBuilder();
        while (true) {
            char c = next();
            if (c == '"') return out.toString();
            need(c >= 0x20, "JSON 字符串含控制字符");
            if (c == '\\') {
                c = next();
                switch (c) {
                    case '"': case '\\': case '/': break;
                    case 'b': c = '\b'; break;
                    case 'f': c = '\f'; break;
                    case 'n': c = '\n'; break;
                    case 'r': c = '\r'; break;
                    case 't': c = '\t'; break;
                    case 'u':
                        need(position + 4 <= text.length(), "JSON Unicode 转义缺失");
                        String hex = text.substring(position, position + 4);
                        need(hex.matches("[0-9a-fA-F]{4}"), "JSON Unicode 转义错误");
                        c = (char) Integer.parseInt(hex, 16); position += 4; break;
                    default: throw new IOException("JSON 转义错误");
                }
            }
            out.append(c);
            need(out.length() <= 1024 * 1024, "JSON 字符串过大");
        }
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> object(Object value) throws IOException {
        if (!(value instanceof Map)) throw new IOException("需要 JSON 对象");
        return (Map<String, Object>) value;
    }

    public static String string(Map<String, Object> map, String key) throws IOException {
        Object value = map.get(key);
        if (!(value instanceof String)) throw new IOException("字段不是字符串: " + key);
        return (String) value;
    }

    public static long integer(Map<String, Object> map, String key) throws IOException {
        Object value = map.get(key);
        if (!(value instanceof Long)) throw new IOException("字段不是整数: " + key);
        return (Long) value;
    }
}
