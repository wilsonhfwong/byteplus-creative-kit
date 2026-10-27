# BytePlus Creative Kit

在 ChatGPT 桌面应用中使用 **Seedream 生成图片、Seedance 生成视频**，并通过 **TOS 上传、管理和复用图片/视频素材**。可选配置 Seed 模型用于文本辅助。

**客户无需打开 CMD 或终端，也无需提前安装 Python 或 Docker。** 插件自带桌面启动器，首次配置后自动准备运行环境。

本说明按 **0.2.5** 版本编写。Windows 用户请使用 0.2.5 或更新版本，本地数据已改为保存在用户文件夹中，具体位置见下方“本地数据”。

## 云端 Linux 版本

云端执行环境请使用独立的 [`byteplus-creative-kit-cloud`](plugins/byteplus-creative-kit-cloud/README.md)。它需要 Python 3.12 和 uv，通过环境变量配置凭据，将生成结果保存在云端工作区。它是云端执行器中的 stdio MCP 插件，不是托管的 HTTPS MCP 服务；当前网页插件安装器会将此 stdio 连接标为“Open in desktop app”。如需在云端工作区运行，请按该版本 README 使用自带 MCP 客户端；上传 ZIP 不会在网页云端宿主中注册工具。

从仓库根目录运行 `python scripts/package_cloud.py`，生成可单独上传的 `dist/byteplus-creative-kit-cloud.zip`。请勿将整个仓库 ZIP 上传到单插件上传入口。

## 安装

**首次从 GitHub 添加仓库前：** ChatGPT 需要能在电脑上找到 Git，才能下载插件仓库。Windows 如尚未安装，请通过 [Git 官方 Windows 下载页](https://git-scm.com/install/windows) 下载 **Git for Windows/x64 Setup**，运行图形安装程序并保留默认选项。安装后完全退出并重新打开 ChatGPT，再添加仓库。整个过程无需输入任何命令。若 Git 已安装但仍提示找不到程序，请先重启 ChatGPT；必要时重启 Windows 后再试。

1. 在 ChatGPT 桌面应用中打开 **Settings → Plugins → Add**，选择添加仓库的选项，填入：

   **https://github.com/wilsonhfwong/byteplus-creative-kit**

2. 按电脑系统选择 **BytePlus Creative Kit · Mac** 或 **BytePlus Creative Kit · Windows** 并安装其中一个。若应用要求确认信任插件或允许本地执行，请先查看提示，再按您的组织要求继续。
3. 点击插件的 **Setup / 设置**，或在新的本地 Work/Codex 对话中输入：

   > 帮我配置 BytePlus Creative Kit。

插件会打开本机配置页面。**所有密钥都在该页面输入，不要发送到聊天中。** 如果浏览器没有自动打开，点击聊天中返回的本机配置链接。

保存后，插件会自动下载运行环境。让 ChatGPT 查询准备状态；就绪后即可使用。安装和配置不会自动提交付费生成或上传媒体。

此插件使用本地文件和本机工具，适用于 Mac（Apple 芯片或 Intel）及 Windows x64 的桌面本地执行环境。网页、手机或云端对话不能运行这套本地启动器。使用哪些模型仍取决于您自己的 BytePlus 账户权限。

## 配置时需要什么

| 准备项 | 用途 |
| --- | --- |
| ModelArk API Key | 调用账户已开通的 Seedream / Seedance 模型。只体验生成时，先填写此项即可。 |
| IAM Access Key 与 Secret Key | 管理素材库和向 TOS 上传文件。与模型 API Key 用途不同。 |
| 现有私有 TOS 存储桶名称 | 上传本地图片或视频；请使用 `ap-southeast-1` 区域，并确保 IAM 凭据有相应权限。 |
| ModelArk 项目 | 素材与生成应使用同一项目；默认 `default`。 |
| Session Token（可选） | 使用临时 IAM 凭据时填写。 |
| Seed 模型或 Endpoint ID（可选） | 需要调用 Seed 进行文本辅助时填写。 |

素材库需已在 BytePlus 控制台开通并完成所需条款确认。插件不自动创建存储桶或开通云服务。

更换账户、存储桶或模型时，直接说“打开 BytePlus Creative Kit 配置”，无需重新安装。密钥输入框留空会保留已保存的值；可选模型和存储桶留空会清除对应配置。

## 可以这样使用

**生成图片**

> 使用我账户可用的 Seedream 模型，生成一张方形的未来城市海报，采用温暖的日落色调，并保存图片。

**上传人物图片并生成视频**

> 请列出我的素材组。如果没有“虚构角色 A”，请创建这个组。把我提供的本地参考图片上传到该组，等到素材变为 Active 后，用 Seedance 2.5 生成一段 5 秒视频：人物自然眨眼、微笑，镜头稳定。请保存视频。

可将图片或视频拖入支持本地文件访问的对话，或告诉 ChatGPT 文件在电脑上的位置。使用您有权使用的原始素材。虚构人物使用 AIGC 素材组；真实人物需先按平台要求完成授权与验证，插件可以复用已验证素材，但不包含真人验证流程。

**使用视频参考**

> 把我提供的本地视频上传到“虚构角色 A”组，等待 Active，再把它作为视频参考，使用 Seedance 2.5 生成一段 5 秒视频并保存。

**查看、复用和管理**

> 列出“虚构角色 A”组中的素材，显示名称、ID、类型和状态。
>
> 复用素材 ID“这里填素材 ID”生成一个新视频，不要重复上传。
>
> 将素材 ID“这里填素材 ID”改名为“角色 A 正面参考图”。
>
> 删除素材 ID“这里填素材 ID”，保留 TOS 原始文件。

**可选 Seed 文本辅助**

> 使用已配置的 Seed 模型，把我的创意整理成适合 Seedance 的提示词，先不要生成视频。

## 素材与结果

本地素材的处理流程：**图片或视频 → 私有 TOS → 素材库登记 → Active → 视频生成**。上传地址和临时签名链接由插件自动处理。

`Processing` 表示平台仍在处理；只有 `Active` 的素材才可用于生成。遇到超时或对话中断时，请先查询原有操作、素材或任务 ID，避免重复上传或重复付费。

生成结果下载到电脑的 **下载 / BytePlus Creative Kit** 文件夹，聊天中也会返回保存位置。模型生成和 TOS 等服务费用由您自己的 BytePlus 账户承担。

素材会保留以便复用。删除素材库中的素材不会删除 TOS 源文件；如需清理源文件，请在相关生成任务结束后到 TOS 控制台处理。

## 常见问题

| 情况 | 处理方式 |
| --- | --- |
| 安装后找不到工具 | 确认插件已启用，并使用桌面应用的本地 Work/Codex 对话；新建对话后通过 `@BytePlus Creative Kit` 调用。 |
| 添加仓库时出现 `failed to run git clone` 和 `program not found` | ChatGPT 未找到 Git。通过上方官方链接安装 Git for Windows，完全退出并重新打开 ChatGPT，再重试添加仓库。 |
| 环境一直在准备或提示失败 | 确认可以访问 GitHub Releases 和 PyPI，再打开配置页面保存重试。无需运行安装命令。 |
| Windows 提示 `Missing expected target directory for Python minor version link` | 更新至 0.2.5 或之后版本，完全退出并重新打开 ChatGPT，再让插件重新打开配置页面，保留密钥栏为空并保存重试。新版使用用户目录并自动带入旧配置，无需移动 ChatGPT 安装目录或运行修复脚本。 |
| 保存配置时提示“请求来源无效” | 更新或重新安装 0.2.5 及之后版本，再从插件重新打开 Setup 页面。旧配置页面不会随插件更新而自动修复。 |
| 能看到设置技能，但找不到 `creative_kit_setup` / `creative_kit_status` | 更新或重新安装 0.2.5 及之后版本，完全退出并重新打开 ChatGPT，再在新对话中配置。早期版本的工具启动路径会被宿主拒绝。 |
| 可以生成，但无法上传素材 | 补充 IAM 凭据、TOS 私有存储桶，并检查素材库和存储桶权限。 |
| 找不到已有素材 | 检查项目是否一致，并确认素材组、素材 ID 和 Active 状态。 |
| 旧版本仍在显示 | 如曾安装命令行版本，可在 MCP 设置中停用旧的 `byteplus_seedance` / `byteplus_seedream`，再使用本插件。云端素材会保留。 |

## 本地数据

配置、密钥和素材记录保存在电脑上的本地数据目录中。默认位置为：

- **Windows：`%USERPROFILE%\.byteplus-creative-kit`**，通常为 **`C:\Users\您的用户名\.byteplus-creative-kit`**。
- Mac：`~/Library/Application Support/BytePlusCreativeKit/`

**从 0.2.5 起，Windows 的 Kit 本地数据不再写入 AppData。** 配置、密钥、素材记录、运行环境、缓存、日志和临时文件统一放在用户文件夹下的上述目录。ChatGPT 安装在 C 盘或 D 盘均不影响上述默认位置，无需移动 ChatGPT 或运行修复脚本。

升级旧版本前，请先完全退出 ChatGPT。新目录不存在时，插件会自动复制旧版的配置及素材记录，并在新目录重新准备运行环境；新目录已存在时不会覆盖其中的数据。旧版 AppData 文件保留作为备份，不再用于 Kit 的新写入。曾显式设置过 AppData 以外自定义目录的用户会继续使用该目录；可让插件查询状态，查看实际保存位置。

密钥采用明文配置文件保存，插件不会把它们写入仓库或返回给聊天。请妥善保管电脑和本地数据目录。

重新安装或升级插件会保留这里的配置和上传记录。卸载插件不会删除 TOS 对象、素材库资源或已经生成的媒体。

开发与打包说明见 [维护说明](docs/MAINTAINER.md)。第三方代码声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

