# doubao-web-sse-client

豆包 Web Python 客户端。

一个基于豆包 Web 请求协议的非官方 Python 项目。使用浏览器完成扫码登录后，程序会保存当前账号的会话信息；后续对话由 Python 直接发送请求并读取 SSE 流。项目包含纯 Python 的 `a_bogus` 签名实现，以及图片和 PPTX 产物下载。

## 功能

- 扫码登录，自动提取 Cookie 和请求参数，保存到本地 `.local/session.json`。
- 支持普通对话、深度思考、联网搜索、图片生成、PPT 生成和帮我写作六种模式。
- 每轮图片生成只保存最后一张完整原图；PPT 模式默认要求生成五页不同内容并导出 `.pptx`。
- 同一进程中保留对话状态，可连续提问或切换模式。
- 提供交互式控制台、单次调用命令和 Python 调用接口。

登录需要可见的 Chrome；登录完成后的聊天请求不依赖浏览器常驻。

## 环境要求

- Python 3.10 或更新版本。
- Google Chrome。扫码登录需要可用的 ChromeDriver；如果系统中没有安装驱动，Selenium Manager 会尝试自动查找。ChromeDriver 的主版本应与 Chrome 匹配。
- 可访问豆包网页和相关接口的网络环境。

## 安装

在项目根目录运行：

```bash
python -m pip install -e .
```

## 快速开始

```bash
python scripts/run.py
```

首次运行或找不到 `.local/session.json` 时，程序会打开登录窗口：

1. 在窗口中勾选登录协议，选择“抖音一键登录”并扫码。
2. 扫码成功后，程序会自动发送一次“你好”以创建对话，并从该请求提取会话参数。
3. 参数保存到项目私有目录下的 `.local/session.json`，登录窗口自动关闭，随后进入模式选择菜单。

终端不会打印 Cookie。`.local/session.json` 包含登录凭据，已列入 [`.gitignore`](./.gitignore)；请不要手动上传该文件或分享其内容。

### 登录开关

编辑 [`run.py`](./run.py) 顶部的 `LOGIN_ENABLED`：

| 值 | 启动行为 |
| --- | --- |
| `False`（默认） | 有 `.local/session.json` 就读取；没有则打开扫码登录窗口 |
| `True` | 每次启动都重新扫码，并更新 `.local/session.json` |

会话失效或需要切换账号时，设为 `True` 后重新运行。扫码完成后可改回 `False`。

## 对话模式

启动后输入数字选择模式：

| 编号 | 模式 | 行为 |
| --- | --- | --- |
| 1 | 普通对话 / 快速 | 常规问答 |
| 2 | 普通对话 / 深度思考 | 打开请求中的深度思考开关 |
| 3 | 普通对话 / 联网搜索 | 通过搜索意图提示触发服务端搜索 |
| 4 | 图像生成 / 快速 | 继续选择 Seedream 型号，只保存本轮最后一张无水印原始图 |
| 5 | PPT 生成 / 快速 | 默认要求五页不同内容，并导出 PPTX |
| 6 | 帮我写作 / 快速 | 写作意图模式 |

图像模式支持 Seedream 5.5、Seedream 5.0 Pro、Seedream 5.0 Flash、
Seedream 4.5 和 Seedream 4.0；未显式选择时默认使用 Seedream 5.5。

例如：

```text
请选择模式 [1-6]> 5
你[PPT 生成/快速]> 人工智能在校园中的应用
豆包> ...
已保存PPT：.../outputs/ppt/人工智能在校园中的应用.pptx
```

控制台支持 `/mode` 切换模式、`/modes` 查看菜单、`/help` 查看帮助；输入 `exit`、`quit` 或 `退出` 结束程序。

图片保存在 `outputs/images/`，PPTX 保存在 `outputs/ppt/`。如果服务端只返回在线卡片，没有返回可下载的 PPT 文件，控制台会明确提示。联网搜索遇到服务端限流时会报告错误，不会自动重试。

## 单次调用与 Python 接口

已经有 `.local/session.json` 时，可直接发送单次请求：

```bash
python -m doubao_sign.cli --session .local/session.json "你好"
```

只构造签名请求、不发送网络请求：

```bash
python -m doubao_sign.cli --session .local/session.json --dry-run "你好"
```

`--dry-run` 输出包含会话相关请求参数，分享日志前请检查内容。

也可以在 Python 中调用：

```python
import json
from pathlib import Path

from doubao_sign.client import DoubaoClient, DoubaoSession

data = json.loads(Path(".local/session.json").read_text(encoding="utf-8"))
client = DoubaoClient(DoubaoSession(**data))

for chunk in client.stream_text("你好"):
    print(chunk, end="")
```

## 项目结构

```text
.
├── src/doubao_sign/       # 可安装的 Python 包
│   ├── abogus.py          # 纯 Python a_bogus 签名
│   ├── artifacts.py       # 图片与 PPTX 的提取、下载和校验
│   ├── client.py          # 请求构造、SSE 解析与对话状态
│   ├── cli.py             # 单次调用命令入口
│   ├── console.py         # 交互式控制台
│   ├── login.py           # 扫码登录与会话保存
│   ├── modes.py           # 六种模式的请求配置
│   └── mstoken.py         # msToken 签发协议
├── scripts/run.py         # 交互式入口及登录开关
├── tests/                 # 单元测试
├── outputs/               # 生成的图片与 PPTX（运行时创建）
├── .local/session.json    # 私有登录会话（运行时创建）
├── pyproject.toml          # 依赖与包配置
└── README.md
```

`.local/` 和 `outputs/` 不纳入版本控制。项目入口位于 `scripts/`，可导入的源码位于 `src/`；运行前先执行安装命令。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖登录开关、会话提取、签名、请求结构、SSE 文本解析和产物处理。真实登录与生成结果依赖当前网页协议及账号状态，不能由离线单元测试保证。

## 实现与兼容性

- 对话使用豆包网页的 `POST /chat/completion` SSE 通道；HTTP 传输由 `curl_cffi` 执行。
- `a_bogus` 由 Python 生成，签名绑定原始 query 和请求体字节；不要在签名后重新排序参数或重新序列化请求体。
- 登录时捕获的 `msToken` 是服务端签发值；更换账号或会话失效时重新扫码。
- 网页接口、意图路由或签名协议发生变化时，可能需要更新客户端。

第三方实现来源见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。项目目前未指定许可证；公开发布前请由项目所有者决定是否添加 `LICENSE`。
