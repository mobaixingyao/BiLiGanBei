# Project: BiLiganbei

哔哩哔哩（Bilibili）视频下载桌面应用：支持二维码登录、视频查询、UP 主投稿、合集/收藏夹批量下载、多任务队列下载，以及弹幕下载（ASS / XML 两种格式）。

## 技术栈

- 语言/运行时：Python 3.9+（当前虚拟环境 `.venv`）
- 框架/核心库：PySide6（GUI）、requests（网络）、qrcode（二维码生成）、Pillow（图片处理）
- 构建/包管理：无打包脚本，依赖见 `requirements.txt`；`pip install PySide6 requests qrcode pillow`
- 基础设施：ffmpeg（音视频合并，需加入系统 PATH）；下载目录默认 `downloads/`，可配置

## 项目结构

- `bilibili_downloader.py` —— 唯一的主程序文件（约 4000+ 行）：Bilibili API 客户端、WBI 签名、弹幕 protobuf 解析与 ASS/XML 生成、Qt 界面、下载队列管理、各类 Worker 线程
- `config.json` —— 用户配置（下载目录、默认清晰度、并发数、弹幕格式等）
- `config/` —— 登录状态缓存（`login_state.json`、`cookies.config`）
- `downloads/` —— 视频下载目录（每个视频独立子文件夹：视频名/视频.mp4 + 弹幕文件）
- `API_LIST.md` —— B 站 API 接口参考
- `.venv/` —— Python 虚拟环境

## 工作流

- 运行开发服务器 / 程序：`.venv\Scripts\python.exe bilibili_downloader.py`
- 语法检查：`.venv\Scripts\python.exe -m py_compile bilibili_downloader.py`
- 依赖安装：`pip install PySide6 requests qrcode pillow`（需与 `.venv` 匹配）
- 代码约定：
  - 单文件结构，模块分区用 `# ==== 区段名 ====` 注释分隔
  - 中文注释说明业务逻辑
  - 网络请求统一通过 `BilibiliClient.session`（线程本地 Session）并带 UA/Referer/Cookie 头
  - 所有耗时操作走 QThread Worker + Signal 回传 UI，避免阻塞主线程
- Git 工作流：仓库 `https://github.com/mobaixingyao/BiLiganbei.git`，无固定分支约定

## 项目记忆

### 弹幕 ASS 布局（PiliPlus 防遮挡改造）

- 弹幕通过 B 站 protobuf 接口 `/x/v2/dm/web/seg.so` 获取（`BilibiliClient.get_danmaku`），每段 6 分钟，按 `segment_index` 递增请求直到无数据
- ASS 生成核心：`_DanmakuLayout` 类做轨道碰撞检测，`_find_track` 为每条弹幕分配 y 坐标轨道
- **历史问题**：弹幕过多时（同刻弹幕数 > 轨道数），所有溢出弹幕会堆到第一行看不清。根因是 `_find_track` 溢出回退把所有弹幕放到 `y_start`（第一轨道）。
- **第一轮修复**（轨道分布）：
  - `_find_track` 溢出时改为复用「最早空闲」的轨道（`_overflow_round` 轮换分散到多行）
  - 轨道高度由 `font_size + 1` 改为 `max(14, int(font_size * 0.8))`
  - 滚动弹幕时长 16.0s → 12.0s
- **第二轮修复**（参照 PiliPlus-main 防遮挡，当前版本）：
  - `_parse_danmaku_elem` 新增解析 **weight 字段（protobuf field 9）**——此前完全未解析
  - 新增 `_merge_danmaku_by_content`：同一 6 分钟分段内相同内容弹幕只保留首条并累计 count，输出 "×N" 徽标，砍掉重复刷屏
  - 权重过滤：`danmaku_weight` 阈值，丢弃 `weight < 阈值` 的弹幕（对应 PiliPlus"智能云屏蔽"）
  - `_find_track` 溢出时默认 `skip_overflow=True` 直接丢弃放不下的弹幕（对应 PiliPlus canvas 碰撞检测跳过），彻底消除水平重叠；`skip_overflow=False` 时保留轮换复用
  - 尺寸对齐 PiliPlus：默认字号 15、行高系数 1.4（`track_height = max(14, int(font_size*line_height))`）、滚动时长 12.0s（**B 站原版速度**；PiliPlus 的 7.0s 太快要改回 12.0）、顶部/底部固定 4.0s、滚动显示区域 `show_area=0.6`
  - **注意**：`get_bottom_y` 在 `_find_track` 返回 None 时必须先判空再 `play_res_y - y - track_height`，否则 TypeError 崩溃
- **ASS 弹幕配置键（config.json，通过 `self.config.get(...)` 读取，未写入文件时用默认值）**：
  `danmaku_font_size`(15)、`danmaku_line_height`(1.4)、`danmaku_show_area`(0.6)、`danmaku_scroll_duration`(12.0)、`danmaku_fix_duration`(4.0)、`danmaku_merge`(True)、`danmaku_weight`(0)、`danmaku_skip_overflow`(True)
- **弹幕不透明度**：ASS Style 的 Primary/Secondary/Outline/Back 颜色使用 `&H00` alpha 前缀，即 **100% 不透明**（ASS 中 `&HAA`=0 为不透明、255 为全透明；曾为 `&H80` 即 50% 半透明，已改为 `&H00`）
- 弹幕格式：ASS（默认，应用合并/过滤/丢弃等防遮挡处理）或 XML（B 站标准格式，**保持原始数据不处理**），在「设置」中切换，由 `config.json` 的 `danmaku_format` 控制

### 关键业务规则

- WBI 签名：`WBISigner` 从 `/x/web-interface/nav` 的 `wbi_img` 取密钥（未登录也能取到），过滤空值参数后再 md5 签名，出错时强制刷新密钥重试
- 下载并发：最多 3 个同时下载（`max_concurrent`，config.json 控制）
- 未登录时 `get_play_url` 添加 `try_look=1` 可预览高清晰度
- 弹幕队列：任务结束后清理 worker 引用必须等 QThread 内置 `finished` 信号（直接删会崩溃）
