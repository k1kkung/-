# SOUP.AI 海龟汤

这是一个使用 pywebview 和本地 Qwen3-4B 模型运行的 Windows 单机海龟汤推理软件原型。

## 当前功能

- 按题材、难度、故事尺度筛选并进行单题抽题。
- 浏览 100 条本地故事题库，支持搜索、筛选和分页。
- 不喜欢当前故事时，可以换一题或标记为不再推荐。
- 每题最多两次提示，可选择使用 AI 提示或本地预写提示。
- 玩家使用自然语言提问，裁判返回“是”“不是”或“与此无关”。
- AI 不可用时自动回退到本地规则模式。
- 桌面模式使用 Python/pywebview 桥接，不启动额外的 FastAPI 服务。

## 技术栈

- Python 3.9+
- pywebview
- llama.cpp `llama-server.exe`
- Qwen3-4B-Instruct-2507 Q4_K_M
- SQLite
- 原生 HTML/CSS/JavaScript

模型和运行时不进入 Git 仓库，需要在本机手动准备。

## 目录结构

```text
backend/
  app.py                    pywebview 入口和本地模型服务管理
  story_repository.py       SQLite 题库、筛选、抽题和偏好
  stories.json              可编辑的故事种子库
  export_frontend_data.py   生成浏览器回退快照
  stories.db                启动时自动生成，不提交 Git
models/
  Qwen3-4B-Instruct-2507-Q4_K_M.gguf
runtime/
  llama-server.exe
  README.txt
app.js
index.html
styles.css
stories.js
start.bat
```

## 快速启动

1. 安装 Python 3.9 或更高版本。
2. 将 `llama-server.exe` 及其依赖文件放到 `runtime\`，确保存在：

```text
runtime\llama-server.exe
```

3. 将模型文件放到：

```text
models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf
```

模型文件大小应为约 `2,497,281,120` 字节。

4. 双击运行：

```text
start.bat
```

`start.bat` 会自动创建 D 盘项目目录下的 `.venv`，安装依赖，并启动桌面窗口。缓存、临时文件和日志分别写入 `cache\` 和 `logs\`。

如果没有放置 `llama-server.exe`，窗口仍然可以打开，但会使用规则模式；AI 裁判和 AI 提示需要本地 runtime 可用。

## 手动安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 协作流程

克隆仓库后建议为每个功能单独建分支：

```powershell
git clone <your-repository-url>
cd "SOUP.AI海龟汤"
git checkout -b feature/your-feature
git add .
git commit -m "描述你的改动"
git push origin feature/your-feature
```

然后在 GitHub 上创建 Pull Request。题库可以直接修改 `backend/stories.json`，再运行：

```powershell
.\.venv\Scripts\python.exe .\backend\export_frontend_data.py
```

生成或更新 `stories.js`。

## 当前限制

- 当前工作目录尚未补齐 `runtime\llama-server.exe`，真实本地模型加载和 AI 裁判仍需要实机验证。
- 模型文件体积较大，不建议提交到普通 Git 仓库；如确实需要托管模型，请使用 GitHub Release、Git LFS 或外部模型存储。
- 本项目是课程原型，未做账号、联网、联机、语音和排行榜功能。
