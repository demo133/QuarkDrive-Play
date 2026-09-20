# QuarkPlay — 夸克网盘 × PotPlayer 桌面应用

把"扫描网盘新增视频 → 生成可播放直链 → 拉起 PotPlayer 边下边播"整条链路打包成一个**双击即用**的 Windows 桌面程序。

- 无需打开命令行，双击 `QuarkPlay.exe` 直接出图形界面
- 无需安装 Python、无需装任何依赖（tkinter 已内置，运行期零第三方库）
- 内置图标；OpenList 服务可在程序内一键启动/停止/探活

---

## 一、适用系统（重要）

| 项目 | 说明 |
|---|---|
| **QuarkPlay.exe** | 仅 **Windows 10 / 11 x64**。PyInstaller 产物与平台绑定，macOS/Linux 需在对应系统重新打包 |
| **PotPlayer** | 仅 Windows（`PotPlayerMini64.exe`） |
| **OpenList** | 服务端跨平台，安装位置自定（如 `C:\openlist\openlist.exe`） |

---

## 二、目录结构

```
quark-potplayer\
├── 夸克网盘-PotPlayer-边下边播方案.html   # 总方案文档
├── scripts\                               # 早期 PowerShell 版脚本（可独立使用）
└── app\                                   # ★ 桌面应用打包工程
    ├── app.py                             # 主程序源码（tkinter，仅标准库）
    ├── make_icon.py                       # 图标生成脚本（Pillow，仅打包期需要）
    ├── icon.ico                           # 应用图标（云朵+播放按钮，多尺寸）
    ├── build.bat                          # ★ 一键打包脚本（双击运行）
    ├── QuarkPlay.spec                     # PyInstaller 自动生成的规格文件
    ├── build\                             # 打包中间产物（可删）
    └── dist\
        └── QuarkPlay.exe                  # ★ 最终交付物（约 10 MB，单文件）
```

### 运行期文件位置（用户目录，卸载/重置就删这个文件夹）

```
%APPDATA%\QuarkPlay\
├── config.json      # 配置（OpenList 地址/账号/PotPlayer 路径/扫描目录等）
├── seen.json        # 已见文件基线（用于 diff 出"新增"，可删 = 重新建基线）
├── new-videos.m3u   # 每次扫描发现的新增视频清单
└── service.log      # 程序内启动的 OpenList 服务输出日志
```

---

## 三、打包步骤（给需要重新打包的人）

环境要求：Windows 10/11 x64 + Python 3.10+（含 tkinter）+ `pip install pyinstaller pillow`。

**方式 A：一键脚本**

双击 `app\build.bat`，成功后产物在 `app\dist\QuarkPlay.exe`。

**方式 B：手动命令**

```bat
cd /d <项目>\quark-potplayer\app
python make_icon.py
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name QuarkPlay --icon icon.ico --add-data "icon.ico;." app.py
```

关键参数说明：

| 参数 | 作用 |
|---|---|
| `--windowed` | 不弹控制台黑窗（GUI 必备） |
| `--onefile` | 单文件 exe，解包到临时目录后运行（启动略慢 1~2 秒属正常） |
| `--icon icon.ico` | exe 与窗口图标 |
| `--add-data "icon.ico;."` | 把图标打进包内 |

---

## 四、首次使用

1. 确认 OpenList 已安装并完成配置（未安装的话按主方案文档配置）。
2. 双击 `QuarkPlay.exe`：程序会**自动检测并启动 OpenList**——未运行时自动拉起（失败自动重试 3 次，原因写入日志页）；系统里已有 OpenList 在跑则直接复用，不会重复启动。
3. 「设置」页核对：OpenList 地址 `http://127.0.0.1:5244`、账号、密码、PotPlayer 路径（按你的实际安装位置）、扫描目录 `/quark`。
4. 「视频库」页点 **扫描**：首次扫描只建立基线不自动播放；之后每次扫描，**新增**的视频会列出，双击即用 PotPlayer 边下边播。
5. 需要挂机自动发现 → 打开「监听」开关，按设置页的间隔（默认 60 秒）自动轮询，发现新视频自动拉起 PotPlayer。
6. **记忆播放进度**：播放时程序自动记录观看位置（每 15 秒保存一次到本地 `progress.json`，纯本地计时、不经过视频流，不影响播放流畅度）。下次打开同一视频自动从上次位置继续，底部会出现橙色提示「已恢复到上次播放位置 时:分:秒」；视频库新增「上次看到」列。右键任意视频可选**从头播放**（清除该片的进度记录）或**清除本片进度记录**。已看完的视频（记录位置超过片尾）从头播放。可在设置页关闭此功能。
6. **退出程序时**，若 OpenList 是由本程序启动的，会弹窗询问：停止并退出 / 保持运行并退出（PotPlayer 还想继续播就选保持）/ 取消返回。

---

## 五、常见问题排查

| 现象 | 原因与处理 |
|---|---|
| 双击 exe 提示 **Windows 已保护你的电脑**（SmartScreen） | 程序未做代码签名，属正常。点「更多信息」→「仍要运行」 |
| **杀毒软件报毒/自动删除** | PyInstaller 单文件程序的常见误报（无签名）。将 `QuarkPlay.exe` 加入白名单后重下 |
| 双击 **完全无反应** | ① 被杀软静默拦截，查杀软日志；② 在 cmd 里手动运行 exe 看具体报错；③ onefile 解包被安全软件干扰，换目录或加白 |
| 启动慢（1~2 秒后才出窗口） | onefile 需先解包到临时目录，正常现象 |
| **打开程序后 OpenList 未启动 / 启动失败** | 程序会自动拉起并重试 3 次；仍失败时看 `%APPDATA%\QuarkPlay\service.log`；设置页路径不对或 5244 端口被占用也会失败；也可手动点「启动 OpenList」 |
| 扫描报 **401/登录失败** | 设置页密码与 OpenList 后台不一致；或 OpenList 未运行 |
| 直链播放 **403** | OpenList 开启了签名校验，程序已自动带 sign；若手动改链接需带完整 `?sign=` 参数 |
| 扫描报 **object not found** | 个别目录网盘侧异常（如失效的分享转存目录），程序已做目录级容错会跳过，不影响其他目录 |
| **点了播放没反应** | 设置页 PotPlayer 路径不对，改成你的实际安装路径 |
| 播放卡顿/起播慢 | 免费网盘单线程限速所致，正常； PotPlayer 里可开启内置加速（选项→播放→网络） |
| 字幕不显示 | 直链播放时 PotPlayer 只拿到流媒体，需手动加载本地同名 `.srt/.ass` 字幕 |
| **续播位置不准** | 进度按播放时长推算（PotPlayer 是独立进程，程序拿不到它的实时进度条），暂停/拖动会造成偏差；偏差大时右键该视频选「从头播放」或「清除进度记录」即可 |
| **重置全部数据** | 退出程序后删除 `%APPDATA%\QuarkPlay\` 整个文件夹，下次启动重建 |

---

## 六、安全与隐私说明

- 密码仅保存在本机 `%APPDATA%\QuarkPlay\config.json`，不上传任何第三方。
- 程序只与本机 OpenList（127.0.0.1:5244）和 PotPlayer 交互；视频流量由 OpenList 直连夸克服务器。
- 程序自动带的 `?sign=` 链接属于永久签名，**请勿外传生成的 m3u/直链**，等于公开网盘读取权限。
