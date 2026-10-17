SOUP.AI 运行包目录
==================

本目录需要放入 llama.cpp 官方 Windows CUDA x64 release 中的完整运行包，
并确保根目录存在：

    runtime\llama-server.exe

获取方式：
1. 打开 llama.cpp 官方 GitHub Releases 页面。
2. 下载 nightly build b11669 的 Windows CUDA 12.4 x64 主程序包。
3. 同时下载 cudart-llama-bin-win-cuda-12.4-x64.zip。
4. 将两个压缩包完整解压到本 runtime 目录，保持 DLL 与 exe 同目录。
5. 不要重复下载或替换 models 目录中的 GGUF 模型文件。

本机已验证：
- llama-b11669-bin-win-cuda-12.4-x64.zip
- cudart-llama-bin-win-cuda-12.4-x64.zip
- llama-server.exe 可正常加载 Qwen3-4B GGUF

如果没有放置 llama-server.exe，程序仍会显示桌面窗口，但会静默使用规则模式。
