# 桌面外壳改造设计(原生窗口 + 系统托盘)

日期:2026-07-06
状态:已定稿,待实施

## 背景与目标

当前交付形态是 PyInstaller 打包的 Flask 应用:双击 exe 会弹出黑色终端窗口,1 秒后跳转系统浏览器打开 `127.0.0.1:5000`。这不像成品桌面软件——有黑窗、依赖外部浏览器、关掉终端即断服务,客户观感"业余"。

目标:改造成 **原生桌面窗口 + 系统托盘图标** 的成品软件,跨 Windows / macOS。**不改任何现有 Flask 路由和业务逻辑**,只在外面套一层桌面外壳。

## 实现边界(硬约束)

- **新增** `desktop.py`(打包唯一入口)
- **微调** `app.py`:移出 `__main__` 里的 `open_browser`/`app.run`;新增 `is_busy()` 状态查询函数;`_ensure_dirs` 保持模块级可被 import 调用
- **更新依赖**:`requirements.txt` 增加 `pywebview`、`pystray`
- **更新打包入口**:`build_win.bat` 打包目标由 `app.py` 改为 `desktop.py`;新增 `build_mac.sh`
- **不动**:现有 Flask 路由、`core/` 业务处理、`config.py` 的路径逻辑(已正确处理 PyInstaller 冻结场景)

## 架构:外壳与内核分离

```
┌─────────────────────────────────────┐
│  desktop.py  (新增,程序唯一入口)      │
│  1. socket 预绑定 127.0.0.1:0 拿空闲端口 → close │
│  2. 后台线程启动 Flask(传入该端口)   │
│  3. pywebview 开原生窗口 → 连该端口   │
│  4. pystray 托盘图标(显示/退出)      │
│  5. 关窗拦截:is_busy() 则确认         │
└─────────────────────────────────────┘
            │ import & 调用(不改业务)
            ▼
┌─────────────────────────────────────┐
│  app.py  (现有 Flask,仅入口/状态微调) │
└─────────────────────────────────────┘
```

开发调试与交付两种模式共存:
- 开发:`python app.py` 仍可直接跑纯浏览器模式(保留调试入口)
- 交付:打包入口是 `desktop.py`,原生窗口 + 托盘

## 组件设计

### 1. 端口获取(socket 预绑定)

不使用 `app.run(port=0)` 后再猜端口(Flask dev server 下不优雅)。改为:

```python
import socket
def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
```

拿到端口后传给 Flask。**已知竞态**:close 到 Flask bind 之间有极小窗口可能被别的进程抢占;本地单机场景概率极低,可忽略,不做重试逻辑。

### 2. Flask 启动(后台线程)

```python
port = _free_port()
threading.Thread(
    target=lambda: app.run(host="127.0.0.1", port=port, threaded=True),
    daemon=True,
).start()
```

启动前调用 `app._ensure_dirs()`(建目录 + 初始化 DB)。窗口打开前需确保 Flask 已能响应——用轮询 `http://127.0.0.1:{port}/` 直到 200(带超时上限,如 10s),避免竞态导致白屏。

### 3. 原生窗口(pywebview)

```python
import webview
window = webview.create_window("账单截图导出系统",
                               f"http://127.0.0.1:{port}", width=1200, height=800)
window.events.closing += on_closing   # 关窗拦截
webview.start()
```

内核:pywebview 默认使用系统内核 —— Windows 用 Edge WebView2,macOS 用系统 WebKit。**不内置 Chromium**(CEF Python 长期缺维护、PyInstaller 打包坑多,与"稳定交付"目标冲突)。

### 4. 状态查询(is_busy)

`app.py` 新增:

```python
def is_busy():
    """导入进行中(供桌面外壳判断是否可安全退出)。"""
    return _progress["state"] == "parsing"
```

桌面层只调 `is_busy()`,不直接理解 `_progress` 内部字符串。

### 5. 关窗与托盘行为

**窗口 ✕(标题栏关闭)= 隐藏到托盘**,进程继续后台运行:
- 若 `is_busy()`:弹确认框"正在导入,确定隐藏到托盘?"(实际不中断导入,仅提示)
- 否则:直接隐藏窗口到托盘

**托盘菜单**:
- **显示 / 恢复窗口**:从托盘唤回窗口
- **退出**:若 `is_busy()` 则二次确认"正在导入,确定退出?中断后需重新导入";确认后终止进程

导入中断安全性:`indexer` 采用批次事务(`begin_batch`/`commit_batch`/`fail_batch`),整批成功才可见,中断不留脏数据,重新导入即可。

## 跨平台差异(已知限制)

- **Windows**:托盘图标在右下角,✕→隐藏→托盘唤回符合 Windows 肌肉记忆,体验自然。老机器极小概率缺 **Edge WebView2 Runtime** 导致白屏 —— 交付包附带 WebView2 bootstrapper 安装器兜底,文档注明"白屏请双击安装 WebView2"。
- **macOS**:无"系统托盘",对应顶部**菜单栏图标**(status bar item)。Mac 窗口 ✕ 的传统语义与 Windows 不同。首版让两平台行为尽量一致(✕→隐藏、托盘退出),Mac 个别边角交互不够"原生"记为已知限制,不阻塞交付。macOS 用系统 WebKit,真·零额外依赖。

## 打包

- **Windows**:`build_win.bat` 打包目标 `app.py` → `desktop.py`;`--noconsole` 去黑窗;保留 `--add-data "web;web"`、`--hidden-import fitz`,补 pywebview/pystray 相关 hidden import。交付包附带 WebView2 安装器。
- **macOS**:新增 `build_mac.sh`,产出 `.app` bundle(`--windowed`),配图标 `.icns`,`--add-data "web:web"`(Mac 用冒号分隔)。

## 依赖变更

`requirements.txt` 新增:
```
pywebview
pystray
```

## 错误处理

- 端口获取失败 / Flask 启动超时:窗口弹错误提示并退出,不静默白屏。
- WebView2 缺失(Win):表现为白屏,由交付文档 + 附带安装器兜底。

## 测试

- 单元:`is_busy()` 在各 `_progress["state"]` 下返回正确布尔;`_free_port()` 返回可用端口。
- 手动:Mac 本机跑 `python desktop.py` 验证窗口、托盘、✕ 隐藏、托盘退出、导入中确认;Windows 打包 exe 后同样走一遍。
- 回归:现有 pytest 全绿(业务未动,应无影响)。

## 非目标(YAGNI)

- 不上 waitress/gunicorn(首版本地壳,dev server 仅绑 127.0.0.1 足够)。
- 不做单实例锁(pywebview 单窗 + 自动端口,双开顶多多一窗,无抢端口崩溃)。
- 不内置 Chromium。
