import cn.local.instrument703t.core.*;
import java.io.*;
import java.net.*;
import java.nio.file.*;

/** JVM driver: actual production verifier and TCP client, no duplicate codec. */
public final class NativeChecks {
    public static void main(String[] args) throws Exception {
        NativePackage.Result pack = NativePackage.verify(new File(args[1]), Files.readAllBytes(Paths.get(args[2])), (at, total) -> {});
        if (args[0].equals("verify")) { System.out.println("VERIFIED " + pack.kind + " " + pack.files + " " + pack.sha256); return; }
        try (Socket socket = new Socket("127.0.0.1", Integer.parseInt(args[3])); NativeOtaClient client = new NativeOtaClient(socket, new NativeOtaClient.Listener() {
            public void checkCancelled() throws IOException { }
            public void version(String version) { System.out.println("VERSION " + version); }
            public void progress(long sent, long total, int percent) throws IOException { if (args[0].equals("cancel") && sent >= 4096) throw new IOException("TEST cancellation"); }
            public void beforeInstall() { System.out.println("INSTALL_CALLBACK"); }
        })) { client.update(new File(args[1]), pack); }
        System.out.println("INSTALL_REQUEST_SENT");
    }
}
