package cn.local.instrument703t.core;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.security.*;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;

/** Verifies the actual TAR sent to the stock receiver. Never extracts or executes files. */
public final class NativePackage {
    public static final long MAX_BYTES = 520L * 1024 * 1024;
    public static final String MODEL = "JC_703T25";
    public static final String FACTORY_SHA = "4fd51af4f1d2dd4f72acf2141cb885043f0a67d1fcdf5065704f69bb485e86ea";
    public static final String FACTORY_VERSION = "JC_703T25_V02.26.02.02.60";
    public static final String MANIFEST = "ota703t/manifest.json", SIGNATURE = "ota703t/manifest.sig";
    public interface Progress { void update(long current, long total) throws IOException; }
    public static final class Result {
        public final String kind, release, baseVersion, sha256, wireName;
        public final long bytes;
        public final int files;
        public final boolean signed;
        Result(String kind, String release, String base, String sha, long bytes, int files, boolean signed) {
            this.kind = kind; this.release = release; this.baseVersion = base; this.sha256 = sha;
            this.bytes = bytes; this.files = files; this.signed = signed;
            wireName = signed ? "JC_703T25_OTA.tar" : FACTORY_VERSION + ".tar";
        }
        public void checkVersion(String current) throws IOException {
            need(current.startsWith(MODEL + "_V"), "仪表型号不匹配");
            need(baseVersion.isEmpty() || baseVersion.equals(current), "包的基线不匹配：需要 " + baseVersion + "，仪表为 " + current);
        }
    }
    private static final class Member {
        final long offset, size, mode;
        Member(long o, long s, long m) { offset = o; size = s; mode = m; }
    }
    public static void need(boolean value, String error) throws IOException { if (!value) throw new IOException(error); }
    public static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder();
        for (byte b : bytes) out.append(String.format(Locale.ROOT, "%02x", b & 255));
        return out.toString();
    }
    public static RSAPublicKey publicKey(byte[] pem) throws Exception {
        String text = new String(pem, StandardCharsets.US_ASCII).trim();
        String start = "-----BEGIN PUBLIC KEY-----", end = "-----END PUBLIC KEY-----";
        need(pem.length <= 8192 && text.startsWith(start) && text.endsWith(end), "内置发布公钥格式错误");
        PublicKey key = KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(Base64.getDecoder().decode(
                text.substring(start.length(), text.length() - end.length()).replaceAll("\\s", ""))));
        need(key instanceof RSAPublicKey, "需要 RSA 发布公钥");
        RSAPublicKey rsa = (RSAPublicKey) key;
        need(rsa.getModulus().bitLength() >= 3072 && rsa.getModulus().bitLength() <= 8192, "发布密钥长度错误");
        return rsa;
    }
    public static String keyId(byte[] pem) throws Exception { return hex(MessageDigest.getInstance("SHA-256").digest(publicKey(pem).getEncoded())); }
    public static String digest(File file, Progress progress) throws Exception {
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] buffer = new byte[65536]; int n; long count = 0;
            while ((n = in.read(buffer)) != -1) { hash.update(buffer, 0, n); count += n; progress.update(count, file.length()); }
        }
        return hex(hash.digest());
    }
    private static boolean zero(byte[] bytes) { for (byte b : bytes) if (b != 0) return false; return true; }
    private static String text(byte[] h, int at, int size) throws IOException {
        int end = at; while (end < at + size && h[end] != 0) { need(h[end] >= 32 && h[end] <= 126, "TAR 名称不是 ASCII"); end++; }
        for (int i = end; i < at + size; i++) need(h[i] == 0, "TAR 名称隐藏数据");
        return new String(h, at, end - at, StandardCharsets.US_ASCII);
    }
    private static long octal(byte[] h, int at, int size) throws IOException {
        String value = new String(h, at, size, StandardCharsets.US_ASCII).replace('\0', ' ').trim();
        need(value.matches("[0-7]{1,12}"), "TAR 数值字段错误");
        try { return Long.parseLong(value, 8); } catch (NumberFormatException e) { throw new IOException("TAR 数值溢出"); }
    }
    private static void safePath(String name) throws IOException {
        need(name.length() <= 200 && !name.startsWith("/"), "TAR 路径越界");
        for (String part : name.split("/", -1)) need(part.matches("[A-Za-z0-9_][A-Za-z0-9_.-]*"), "TAR 路径不规范");
    }
    private static byte[] read(RandomAccessFile f, Member m, int limit) throws IOException {
        need(m != null && m.size <= limit, "清单或签名缺失、过大");
        byte[] raw = new byte[(int) m.size]; f.seek(m.offset); f.readFully(raw); return raw;
    }
    public static Result verify(File file, byte[] pem, Progress progress) throws Exception {
        need(file.length() >= 1024 && file.length() <= MAX_BYTES && file.length() % 512 == 0, "请选择原厂全量 TAR 或已签名的原厂协议 TAR");
        String sha = digest(file, progress);
        if (FACTORY_SHA.equals(sha)) return new Result("full", FACTORY_VERSION, "", sha, file.length(), 110, false);
        try (RandomAccessFile f = new RandomAccessFile(file, "r")) {
            Map<String, Member> members = new LinkedHashMap<>(); boolean ended = false; byte[] h = new byte[512];
            while (f.getFilePointer() + 512 <= f.length()) {
                f.readFully(h);
                if (zero(h)) {
                    f.readFully(h); need(zero(h), "TAR 结束标记不完整");
                    while (f.getFilePointer() < f.length()) { f.readFully(h); need(zero(h), "TAR 结束后有额外数据"); }
                    ended = true; break;
                }
                long sum = 0; for (int i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? 32 : h[i] & 255;
                need(sum == octal(h, 148, 8), "TAR 头校验失败");
                need(new String(h, 257, 8, StandardCharsets.US_ASCII).equals("ustar\000" + "00"), "自制包必须是 USTAR");
                need(h[156] == '0' || h[156] == 0, "自制包只允许普通文件，拒绝链接、设备、目录及扩展头");
                String name = text(h, 0, 100), prefix = text(h, 345, 155); if (!prefix.isEmpty()) name = prefix + "/" + name;
                safePath(name); need(!members.containsKey(name) && members.size() < 4098, "TAR 成员重复或过多");
                long size = octal(h, 124, 12), mode = octal(h, 100, 8), at = f.getFilePointer();
                need(size <= MAX_BYTES && (mode == 0644 || mode == 0755), "TAR 长度或权限错误");
                need(at + ((size + 511) / 512) * 512 <= f.length(), "TAR 内容被截断");
                need(octal(h, 108, 8) == 0 && octal(h, 116, 8) == 0 && octal(h, 136, 12) == 0, "自制包归属或时间错误");
                need(text(h, 265, 32).isEmpty() && text(h, 297, 32).isEmpty() && text(h, 157, 100).isEmpty(), "自制包包含非规范的归属或链接字段");
                members.put(name, new Member(at, size, mode)); f.seek(at + ((size + 511) / 512) * 512);
            }
            need(ended, "TAR 缺少结束标记");
            for (String name : members.keySet()) {
                for (int slash = name.indexOf('/'); slash >= 0; slash = name.indexOf('/', slash + 1))
                    need(!members.containsKey(name.substring(0, slash)), "TAR 文件与目录冲突");
            }
            byte[] raw = read(f, members.get(MANIFEST), 1024 * 1024), sig = read(f, members.get(SIGNATURE), 1024);
            Signature verifier = Signature.getInstance("SHA256withRSA"); RSAPublicKey key = publicKey(pem);
            need(sig.length == (key.getModulus().bitLength() + 7) / 8, "签名长度错误");
            verifier.initVerify(key); verifier.update(raw); need(verifier.verify(sig), "发布签名不匹配或包被修改");
            String json = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(raw)).toString();
            Map<String, Object> m = StrictJson.object(StrictJson.parse(json));
            need(m.keySet().equals(new HashSet<>(Arrays.asList("schema", "model", "kind", "release", "base_version", "key_id", "files", "test_script", "rollback_script"))), "清单字段缺失或不支持");
            need(StrictJson.string(m, "schema").equals("703t-native-ota-v1") && StrictJson.string(m, "model").equals(MODEL), "包格式或机型不匹配");
            need(StrictJson.string(m, "key_id").equals(keyId(pem)), "发布身份不匹配");
            String kind = StrictJson.string(m, "kind"), release = StrictJson.string(m, "release"), base = StrictJson.string(m, "base_version");
            need(kind.equals("full") || kind.equals("incremental"), "只支持全量与文件增量包");
            need(release.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,47}"), "发布号错误");
            need(base.isEmpty() || base.matches("JC_703T25_V[0-9.]{1,30}"), "适用版本格式错误");
            need(!kind.equals("incremental") || !base.isEmpty(), "增量包必须指定适用的仪表版本");
            Object rows = m.get("files"); need(rows instanceof List, "文件清单格式错误");
            Set<String> expected = new HashSet<>(Arrays.asList(MANIFEST, SIGNATURE)); long done = 0;
            byte[] buffer = new byte[65536];
            for (Object value : (List<?>) rows) {
                Map<String, Object> row = StrictJson.object(value);
                need(row.keySet().equals(new HashSet<>(Arrays.asList("path", "size", "mode", "sha256"))), "文件条目字段错误");
                String path = StrictJson.string(row, "path"); safePath(path); need(expected.add(path), "文件清单重复");
                Member member = members.get(path); need(member != null && member.size == StrictJson.integer(row, "size") && member.mode == StrictJson.integer(row, "mode"), "文件长度或权限不匹配");
                String hash = StrictJson.string(row, "sha256"); need(hash.matches("[0-9a-f]{64}"), "文件哈希格式错误");
                MessageDigest digest = MessageDigest.getInstance("SHA-256"); f.seek(member.offset); long left = member.size;
                while (left > 0) { int count = (int) Math.min(left, buffer.length); f.readFully(buffer, 0, count); digest.update(buffer, 0, count); left -= count; done += count; progress.update(done, file.length()); }
                need(hash.equals(hex(digest.digest())), "载荷被修改：" + path);
            }
            need(expected.size() > 2 && expected.equals(members.keySet()), "缺失或未声明的 TAR 文件");
            if (kind.equals("incremental")) {
                for (String field : new String[]{"test_script", "rollback_script"}) {
                    String path = StrictJson.string(m, field); Member member = members.get(path);
                    need(!path.equals(MANIFEST) && !path.equals(SIGNATURE) && member != null && member.size > 0 && member.mode == 0755 && path.endsWith(".sh"), "增量包缺少可执行的测试/回退脚本");
                }
                need(!StrictJson.string(m, "test_script").equals(StrictJson.string(m, "rollback_script")), "测试与回退脚本不能相同");
                need(members.containsKey("updateFile_GT.sh") && members.containsKey("updateFile_HW.sh"), "增量包缺少面板安装入口");
            } else {
                need(StrictJson.string(m, "test_script").isEmpty() && StrictJson.string(m, "rollback_script").isEmpty(), "全量包清单策略错误");
            }
            return new Result(kind, release, base, sha, file.length(), members.size() - 2, true);
        }
    }
}
