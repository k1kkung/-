# SOUP.AI 海龟汤

这是一个使用 pywebview 和本地 Qwen3-4B 模型运行的 Windows 单机海龟汤推理软件原型。

## 当前功能

- 按题材、难度、故事尺度筛选并进行单题抽题。
- 浏览 100 条本地故事题库，支持搜索、筛选和分页。
- 不喜欢当前故事时，可以换一题或标记为不再推荐。
- 每题最多两次提示，可选择使用 AI 提示或本地预写提示。
- 提示会在需要时附带一条可点击的二元参考问法，不再常驻展示示例问题。
- 玩家使用自然语言提问，裁判基于完整汤底返回“是”“不是”“与此无关”或“无法判断”。
- AI 裁判以汤底为主要依据，事实表作为参考索引，并要求返回可校验的证据原文。
- 裁判会携带最近 6 轮问答，用于理解“他、她、这件事、后来”等指代。
- 模型自报置信度低于阈值或证据无效时返回“无法判断”；模型不可用时回退本地规则。
- 50 题题库包含短摘要，揭晓弹窗默认显示摘要，可按需展开完整汤底。
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
  stories_bali_50.json      八里十原创海龟汤 50 题整理题库
  stories_horror_v1.json    惊悚反转原创改编题库草稿
  export_frontend_data.py   生成浏览器回退快照
  evaluate_judge.py         运行固定案例的裁判评测
  judge_cases.json          带预期答案的裁判验收集
  validate_story_bank.py    校验自定义题库结构
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
tests/
  test_judge.py             裁判接口与证据校验测试
  run_frontend_tests.js     前端规则回退测试
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

使用“八里十原创海龟汤”50 题题库启动：

```text
start_bali_50.bat
```

该入口会自动切换题库 JSON、SQLite 和前端回退快照，不影响默认 `stories.json` 题库。

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

## 测试与评测

运行后端单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

运行前端规则测试：

```powershell
node .\tests\run_frontend_tests.js
```

验证独立题库：

```powershell
.\.venv\Scripts\python.exe .\backend\validate_story_bank.py .\backend\stories_horror_v1.json
```

启动本地模型并运行固定裁判验收集：

```powershell
.\.venv\Scripts\python.exe .\backend\evaluate_judge.py
```

评测输出包含整体准确率、规则回退数量和“是/不是”严重答反数量。`self_confidence` 是模型自报的主观置信度，不等同于经过校准的正确率。

## 当前状态

- 本机已配置 llama.cpp nightly `b11669` CUDA 12.4 Windows x64 runtime，并已验证 GGUF 模型成功加载。
- 当前 14 条固定验收集在真实 Qwen3-4B 上准确率为 92.9%，严重答反为 0；仍存在 `unknown/irrelevant` 边界误判。
- 已整理八里十原创海龟汤 50 题，每题包含 5 条带汤底原文证据的事实、2 条提示和 3 条二元示例问题。
- 50 题题库当前标注为“需人工复核”，正式公开前必须取得原作者授权。
- AI 提示仍使用本地模型生成，提示质量需要继续通过独立验收集评估。
- 模型文件和 runtime 二进制不会提交到 Git；合作者需要在本地按上面的目录结构准备。
- 模型文件体积较大，不建议提交到普通 Git 仓库；如确实需要托管模型，请使用 GitHub Release、Git LFS 或外部模型存储。
- 本项目是课程原型，未做账号、联网、联机、语音和排行榜功能。
