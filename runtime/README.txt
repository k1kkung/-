SOUP.AI 运行包目录
==================

本目录需要放入 llama.cpp 官方 Windows CUDA x64 release 中的完整运行包，
并确保根目录存在：

    runtime\llama-server.exe

获取方式：
1. 打开 llama.cpp 官方 GitHub Releases 页面。
2. 在最新正式版本的 Assets 中下载名称包含 windows、cuda、x64 的压缩包。
3. 解压后，把压缩包内的可执行文件和依赖文件放入本 runtime 目录。
4. 不要重复下载或替换 models 目录中的 GGUF 模型文件。

如果没有放置 llama-server.exe，程序仍会显示桌面窗口，但会静默使用规则模式。
