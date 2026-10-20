# 维护说明

仓库包含 Mac 和 Windows 两个插件条目；客户添加同一个仓库后，选择对应操作系统的条目安装，不需要手工执行任何脚本。

- `plugin.template.json`：插件元数据模板。
- `.agents/plugins/marketplace.json`：指向 `plugins/` 下两个系统版本的条目。
- `plugins/*/plugin.json` / `mcp.json`：Agent Plugins 格式，包含本地 MCP 和 onboarding skill。
- `plugins/*/.codex-plugin/plugin.json` / `.mcp.json`：旧客户端兼容配置，由构建脚本生成。
- `native-launcher/`：无第三方依赖的 Go 启动器、配置页面、MCP 发现与工具转发。
- `byteplus_creative/` / `packages/`：现有 Python SDK、生成与素材管理工具。
- `plugins/byteplus-creative-kit-mac/bin/creative-kit`：Mac arm64 / amd64 通用可执行文件。
- `plugins/byteplus-creative-kit-windows/bin/creative-kit.exe`：Windows x64 可执行文件，manifest 显式使用 `.exe`，避免不同宿主的可执行文件解析差异。

启动器立即响应 MCP 初始化和工具发现。配置完成后，后台下载固定版本 uv 并校验 SHA-256，再按 `uv.lock` 安装自己的 Python 环境。没有配置或运行环境未准备好时，不会发出云端生成/上传请求。Python 工具的丢失响应不会由启动器自动重放。

本地配置页面只监听 127.0.0.1，使用随机能力路径、Origin/Host 与 CSRF 检查，不显示已保存的密钥。工具状态只返回配置是否齐全。更改凭据后，下次工具调用会重新启动私有工作进程；本地上传数据库保存在安装缓存外，以便升级后复用。

## 开发

维护者需要 Python 3.12、uv 和 Go。客户不需要这些预装工具。

```sh
uv sync --locked --all-groups
uv run python -m byteplus_creative.plugin_server --export-tools > native-launcher/tools.json
cd native-launcher
go test ./...
cd ..
python scripts/build_native.py
```

构建 Mac 通用文件需要 macOS 的 lipo；Windows 文件通过 Go 交叉编译。构建脚本同步旧版兼容 manifest，并记录可执行文件校验值。不要提交配置、缓存、运行日志、个人素材或生成结果。

GitHub Actions 会在 Mac 和 Windows 上验证原生启动器的 MCP 连接、配置页面与 Python 工具接通。自动化检查不使用 BytePlus 凭据，也不会发起付费生成。

兼容格式和仓库 marketplace 依据 [OpenAI 插件打包文档](https://developers.openai.com/plugins/build/plugins)。Onboarding 依据 [OpenAI MCP Extensions](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md#plugin-onboarding)。
