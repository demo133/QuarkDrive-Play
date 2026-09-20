# QuarkDrive-Play

夸克网盘视频「边下边播」工具集：视频存在网盘里，无需下载完整文件，直接在本地 PotPlayer 中播放。

包含两个使用方式，任选其一：

| 方式 | 适合人群 | 说明 |
|---|---|---|
| **QuarkPlay 桌面应用**（推荐） | 所有人 | 双击即用的图形界面，一键扫描网盘视频、双击播放、可挂机监听新视频自动播放 |
| **PowerShell 脚本包** | 喜欢脚本/自定义的人 | 扫描、监听、直链播放、rclone 挂载盘符、浏览器协议处理器等独立脚本 |

## 原理

夸克网盘没有官方 WebDAV。本项目通过开源的 [OpenList](https://github.com/OpenListTeam/OpenList)（Alist 社区分支）接入夸克网盘，生成 HTTP 直链，PotPlayer 直接拉流播放（支持 Range/206，可拖进度条）。详见 `夸克网盘-PotPlayer-边下边播方案.html`。

> ⚠️ 第三方接入方式存在被夸克风控的可能，请知悉风险。

## 快速开始（桌面应用）

1. 安装并配置 OpenList，添加夸克网盘存储（步骤见方案文档）
2. 进入 `app/`，双击 `build.bat` 打包出 `dist/QuarkPlay.exe`（或直接运行 `app.py`）
3. 双击打开程序 → **会自动启动 OpenList 服务**（未运行时自动拉起，失败自动重试 3 次）→ 「设置」页填好地址/账号/PotPlayer 路径 → 「视频库」页扫描播放
4. 关闭程序时如 OpenList 由程序启动，会询问是否一并停止

详细说明见 `app/README.md`。

## 快速开始（脚本包）

1. `cd scripts`
2. `copy config.example.ps1 config.ps1`，填入你的 OpenList 密码和 PotPlayer 路径
3. `.\watch-new.ps1` 扫描新视频并自动播放；加 `-Watch` 常驻监听

其他脚本：`mount-quark.ps1`（rclone 挂盘符）、`play-url.bat` + `register-quarkplay.reg`（注册 `quarkplay:` 协议）。

## 目录结构

```
quark-potplayer/
├── 夸克网盘-PotPlayer-边下边播方案.html   # 完整方案文档（三方案对比、配置、排查）
├── app/                                   # QuarkPlay 桌面应用（tkinter，仅标准库）
│   ├── app.py                             # 主程序源码
│   ├── make_icon.py                       # 图标生成
│   ├── build.bat                          # 一键打包（PyInstaller）
│   └── README.md                          # 应用文档：打包/使用/排查
└── scripts/                               # PowerShell 脚本包
    ├── config.example.ps1                 # 配置模板（复制为 config.ps1 后填写）
    ├── watch-new.ps1                      # 扫描/监听新视频 → 播放
    ├── play-url.ps1 / .bat                # quarkplay: 协议处理
    ├── register-quarkplay.reg             # 注册协议（当前用户，免管理员）
    ├── mount-quark.ps1                    # rclone 挂载为盘符
    └── mount-autostart.bat                # 挂载开机自启（可选，rclone 方案）
```

## 环境要求

- Windows 10/11 x64（PotPlayer 仅 Windows）
- Python 3.10+（含 tkinter）+ PyInstaller + Pillow（仅打包桌面应用时需要）
- OpenList 服务端（跨平台，单文件）

## 隐私说明

- 网盘密码只保存在本机（`config.ps1` 或应用配置目录），仓库中不含任何真实凭据
- 生成的直链带永久签名，等同于网盘读取权限，请勿外传
- 运行产物（`seen-videos.txt`、`new-videos.m3u`）包含个人文件名，已在 `.gitignore` 中排除

## License

MIT
