package cn.local.instrument703t;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.hardware.Camera;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.RGBLuminanceSource;
import com.google.zxing.ReaderException;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.qrcode.QRCodeReader;

import java.io.IOException;
import java.io.InputStream;
import java.util.Collections;
import java.util.Comparator;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@SuppressWarnings("deprecation")
public final class InstrumentQRScanner extends Activity implements SurfaceHolder.Callback, Camera.PreviewCallback {
    static final String EXTRA_CODE = "instrument_wifi_code";
    private static final int PICK_IMAGE = 1;
    private static final int CAMERA_PERMISSION = 2;
    private final QRCodeReader reader = new QRCodeReader();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService photoDecoder = Executors.newSingleThreadExecutor();
    private Camera camera;
    private final Runnable nextFrame = () -> {
        if (camera != null) camera.setOneShotPreviewCallback(this);
    };
    private boolean resumed;
    private boolean decodingPhoto;
    private Camera.Size frameSize;
    private FrameLayout previewBox;
    private SurfaceView preview;
    private TextView instructions;
    private Button selectPhoto;

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setBackgroundColor(Color.BLACK);
        page.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        instructions = new TextView(this);
        instructions.setText("对准仪表投屏页面上的 Wi-Fi 二维码");
        instructions.setTextSize(17);
        instructions.setTextColor(Color.WHITE);
        instructions.setGravity(Gravity.CENTER);
        int inset = Math.round(16 * getResources().getDisplayMetrics().density);
        instructions.setPadding(inset, inset, inset, inset);
        page.addView(instructions);

        previewBox = new FrameLayout(this);
        preview = new SurfaceView(this);
        previewBox.addView(preview, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        preview.getHolder().addCallback(this);
        page.addView(previewBox, new LinearLayout.LayoutParams(-1, 0, 1));

        selectPhoto = new Button(this);
        selectPhoto.setText("从相册选二维码");
        selectPhoto.setOnClickListener(view -> selectPhoto());
        page.addView(selectPhoto, new LinearLayout.LayoutParams(-1, -2));
        Button cancel = new Button(this);
        cancel.setText("取消扫码");
        cancel.setOnClickListener(view -> finish());
        page.addView(cancel, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(page);
        if (saved == null && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION);
        }
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        openCamera(preview.getHolder());
    }

    @Override protected void onPause() {
        resumed = false;
        closeCamera();
        super.onPause();
    }

    @Override protected void onDestroy() {
        photoDecoder.shutdownNow();
        super.onDestroy();
    }

    private void selectPhoto() {
        if (Build.VERSION.SDK_INT >= 33) {
            try {
                startActivityForResult(new Intent(MediaStore.ACTION_PICK_IMAGES).setType("image/*"), PICK_IMAGE);
                return;
            } catch (ActivityNotFoundException unavailable) { /* Try the document picker below. */ }
        }
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*");
        try { startActivityForResult(picker, PICK_IMAGE); }
        catch (ActivityNotFoundException unavailable) { instructions.setText("系统图片选择器不可用。"); }
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request != CAMERA_PERMISSION) return;
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            openCamera(preview.getHolder());
        } else {
            instructions.setText("相机未授权，可以从相册选二维码。");
        }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK_IMAGE || result != RESULT_OK || data == null || data.getData() == null) return;
        decodingPhoto = true;
        closeCamera();
        selectPhoto.setEnabled(false);
        instructions.setText("正在识别二维码…");
        Uri uri = data.getData();
        photoDecoder.execute(() -> {
            try {
                String code = decodePhoto(uri);
                InstrumentWifiCode.parse(code);
                runOnUiThread(() -> { if (!isFinishing() && !isDestroyed()) deliver(code); });
            } catch (ReaderException invalid) {
                photoError("这张图片中没有识别到二维码，请选择更清晰的图片。");
            } catch (IllegalArgumentException invalid) {
                photoError(invalid.getMessage());
            } catch (IOException | SecurityException unreadable) {
                photoError("无法打开这张图片，请重新选择。");
            }
        });
    }

    private String decodePhoto(Uri uri) throws IOException, ReaderException {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inJustDecodeBounds = true;
        try (InputStream stream = getContentResolver().openInputStream(uri)) {
            BitmapFactory.decodeStream(stream, null, options);
        }
        if (options.outWidth <= 0 || options.outHeight <= 0) throw new IOException();
        options.inSampleSize = 1;
        while (Math.max(options.outWidth, options.outHeight) / options.inSampleSize > 2048) options.inSampleSize *= 2;
        options.inJustDecodeBounds = false;
        Bitmap bitmap;
        try (InputStream stream = getContentResolver().openInputStream(uri)) {
            bitmap = BitmapFactory.decodeStream(stream, null, options);
        }
        if (bitmap == null) throw new IOException();
        try {
            int width = bitmap.getWidth(), height = bitmap.getHeight();
            int[] pixels = new int[width * height];
            bitmap.getPixels(pixels, 0, width, 0, 0, width, height);
            RGBLuminanceSource image = new RGBLuminanceSource(width, height, pixels);
            return new QRCodeReader().decode(new BinaryBitmap(new HybridBinarizer(image)),
                    Collections.singletonMap(DecodeHintType.TRY_HARDER, true)).getText();
        } finally {
            bitmap.recycle();
        }
    }

    private void photoError(String message) {
        runOnUiThread(() -> {
            if (isFinishing() || isDestroyed()) return;
            decodingPhoto = false;
            selectPhoto.setEnabled(true);
            instructions.setText(message);
            openCamera(preview.getHolder());
        });
    }

    @Override public void surfaceCreated(SurfaceHolder holder) { openCamera(holder); }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { }
    @Override public void surfaceDestroyed(SurfaceHolder holder) { closeCamera(); }

    private void openCamera(SurfaceHolder holder) {
        if (!resumed || decodingPhoto || camera != null || !holder.getSurface().isValid()) return;
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return;
        try {
            Camera.CameraInfo info = new Camera.CameraInfo();
            int cameraCount = Camera.getNumberOfCameras();
            if (cameraCount == 0) throw new IOException();
            int index = 0;
            for (int i = 0; i < cameraCount; i++) {
                Camera.getCameraInfo(i, info);
                if (info.facing == Camera.CameraInfo.CAMERA_FACING_BACK) {
                    index = i;
                    break;
                }
            }
            Camera.getCameraInfo(index, info);
            camera = Camera.open(index);
            Camera.Parameters settings = camera.getParameters();
            Camera.Size size = Collections.min(settings.getSupportedPreviewSizes(), Comparator.comparingInt(
                    value -> Math.abs(value.width * value.height - 640 * 480)));
            settings.setPreviewSize(size.width, size.height);
            settings.setPreviewFormat(ImageFormat.NV21);
            if (settings.getSupportedFocusModes().contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE)) {
                settings.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
            }
            camera.setParameters(settings);
            frameSize = camera.getParameters().getPreviewSize();

            int degrees = 90 * getWindowManager().getDefaultDisplay().getRotation();
            int orientation = info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT
                    ? (720 - info.orientation - degrees) % 360 : (360 + info.orientation - degrees) % 360;
            camera.setDisplayOrientation(orientation);
            camera.setPreviewDisplay(holder);
            camera.startPreview();
            previewBox.post(() -> fitPreview(orientation));
            nextFrame.run();
        } catch (RuntimeException | IOException error) {
            closeCamera();
            instructions.setText("无法启动相机，请检查权限或改用手动连接。");
        }
    }

    private void fitPreview(int orientation) {
        if (camera == null) return;
        boolean sideways = orientation % 180 != 0;
        int width = sideways ? frameSize.height : frameSize.width;
        int height = sideways ? frameSize.width : frameSize.height;
        double scale = Math.min((double) previewBox.getWidth() / width, (double) previewBox.getHeight() / height);
        if (scale > 0) {
            preview.setLayoutParams(new FrameLayout.LayoutParams((int) (scale * width), (int) (scale * height), Gravity.CENTER));
        }
    }

    @Override public void onPreviewFrame(byte[] frame, Camera source) {
        if (source != camera) return;
        if (frame != null && frame.length >= frameSize.width * frameSize.height) {
            try {
                String code = decode(reader, frame, frameSize.width, frameSize.height);
                InstrumentWifiCode.parse(code);
                deliver(code);
                return;
            } catch (ReaderException ignored) {
                // A frame can contain no recognizable QR code.
            } catch (IllegalArgumentException invalid) {
                instructions.setText(invalid.getMessage());
            }
        }
        handler.postDelayed(nextFrame, 180);
    }

    private void deliver(String code) {
        setResult(RESULT_OK, new Intent().putExtra(EXTRA_CODE, code));
        finish();
    }

    static String decode(QRCodeReader reader, byte[] frame, int width, int height) throws ReaderException {
        PlanarYUVLuminanceSource image = new PlanarYUVLuminanceSource(frame, width, height, 0, 0, width, height, false);
        return reader.decode(new BinaryBitmap(new HybridBinarizer(image))).getText();
    }

    private void closeCamera() {
        handler.removeCallbacks(nextFrame);
        Camera current = camera;
        camera = null;
        if (current == null) return;
        try {
            current.setPreviewCallback(null);
            current.stopPreview();
        } catch (RuntimeException ignored) {
            // The camera may disconnect while the app is in the background.
        } finally {
            current.release();
        }
    }
}
