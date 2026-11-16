# 第三方组件

本项目自有源码及文档采用 [MIT](LICENSE)。下列组件各自遵循原许可证；原厂固件、应用和提取文件不属于本项目许可证，也不在仓库内分发。

| 组件 | 用途 | 来源及许可证 |
| --- | --- | --- |
| Dropbear 2026.94 | 仪表 SSH 服务 | 构建时从 `https://dropbear.nl/mirror/releases/dropbear-2026.94.tar.bz2` 下载，校验 SHA-256；随包合并上游 `LICENSE`、`libtomcrypt/LICENSE`、`libtommath/LICENSE` |
| musl libc | AArch64 静态链接运行库 | [许可证副本](tools/ssh703t/LICENSE.musl)，随 Dropbear 载荷携带 |
| ZXing core 3.5.4 | 安卓相机与相册二维码解码 | Maven 坐标 `com.google.zxing:core:3.5.4`，Apache-2.0；[许可证](android/assets/licenses/ZXing.txt) 随 APK 分发 |

ZXing JAR 保留在 `android/libs/`，用于离线构建。SHA-256：

```text
71de5d89341b5fcf5dd89da7f44e84d825d0e084cdf3ec77c9abe26b0f0ceb13
```

Dropbear 源码归档 SHA-256：

```text
e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81
```
