# 维护说明

仓库包含 Mac 和 Windows 两个插件条目；客户添加同一个仓库后，选择对应操作系统的条目安装，不需要手工执行任何脚本。

仓库导入由 ChatGPT 宿主调用 Git 完成。Windows 干净机器需先通过官方图形安装程序安装 Git，并重启 ChatGPT 以加载新的 PATH。插件尚未下载时无法自行补齐这一宿主依赖。原生 MCP 和浏览器配置测试不覆盖宿主的仓库克隆步骤；交付验收还需实际走一次 Add marketplace 安装流程。

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

配置页面还有真实浏览器回归测试：`python tests/browser_setup.py`（维护者需先安装 Python Playwright 和 Chromium）。Windows CI 同时运行 `python tests/browser_setup.py --browser edge`，使用 Microsoft Edge。测试让浏览器正常提交实际 HTML 表单，检查浏览器自动生成的 Origin、配置落盘及成功提示；仅使用临时虚构密钥，不下载运行环境或调用云端接口。`go test` 默认跳过需要浏览器驱动的夹具。

配置页的 `Referrer-Policy` 必须保留为 `same-origin`。`no-referrer` 会令普通表单 POST 发送 `Origin: null`，被现有来源检查拒绝。不要放宽 Origin、Host 或 CSRF 检查来规避此问题。

发布前还需运行宿主集成检查：`python tests/codex_host_integration.py --codex /path/to/codex`。该测试通过真正的 Codex app-server 读取两个平台的插件包，并发现当前平台原生 MCP 工具；使用隔离配置和空凭据，不登录或调用模型。直接启动 MCP 的测试无法覆盖宿主拒绝 manifest 的情况。

便携 `mcp.json` 中的 `command` 必须使用 `./bin/creative-kit` 或 `./bin/creative-kit.exe`。Agent Plugins 不在 `command` 中展开 `${PLUGIN_ROOT}`；它只在 `args`、`env` 和 `cwd` 中展开。参见 [官方 MCP 配置规范](https://agent-plugins.org/plugin-authors/mcp-servers)。否则宿主会拒绝工具配置，同时继续显示技能。

兼容格式和仓库 marketplace 依据 [OpenAI 插件打包文档](https://developers.openai.com/plugins/build/plugins)。Onboarding 依据 [OpenAI MCP Extensions](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md#plugin-onboarding)。
