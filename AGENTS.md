# OpenVam 图文交付

本仓库接收图文制作任务的最终 ZIP。云端批次使用已配置的 `deliveries` 环境，交付目的地为私有仓库 `bao270026-sys/deliveries`。用户指定其他交付方式时按当次要求执行。

- 在持有成品的制作任务内完成打包和上传。如果从默认环境启动，先用已连接的 GitHub 在同一任务检出本仓库，再继续使用现有成品。尚未取得成品时，按用户指定的文件名和资料库文件识别原件。
- 完成批次校验后使用制作流程产生的完整 ZIP。OpenVam 生图技能先执行 `render_tasks.py finalize`，再用同一版技能的 `recovery.py delivery --root <批次目录> --output <批次外的最终ZIP>` 打包。已有最终 ZIP 时直接使用。把本次完整 ZIP 作为唯一的交付文件。

在仓库根目录用同一条命令交付成品。图文批次传最终 ZIP；用户点名交付其他文件时，传指定原件。支持单个 1 GiB（1,073,741,824 字节）文件。

```sh
python3 scripts/publish_openvam.py "/path/to/成品文件"
```

脚本自动选择传输方式。至多 100 MiB 的 ZIP 按原名保存到 `main/openvam/`，并核对远端 Git blob。更大的 ZIP 和其他指定文件直接上传至同一私库的 Releases，每个成品保留一个完整附件，返回下载链接。Release 上传使用已登录的 GitHub CLI 或它支持的现有令牌，按 GitHub 返回的字节数和 SHA-256 校验。两条路径均支持相同内容重试。

如果小 ZIP 的 Git 传输受限，可用同一私库的 Release 入口交付。GitHub 接受小于 2 GiB 的单个 Release 附件。

```sh
python3 scripts/publish_openvam_release.py "/path/to/完整批次.zip"
```

制作环境只有 GitHub 网页登录态时，可在本私库的 Releases 新建发布并上传同一原件。ZIP 标签使用 `openvam-<64 位小写 SHA-256>`，其他文件使用 `delivery-<64 位小写 SHA-256>`。目标选择 `main`，正文单独写一行 `原始文件名：<完整原文件名>`。附件上传完成后发布。

仓库工作流 `Publish OpenVam release ZIP` 会核对带 `openvam-` 标签的发布附件，将不超过 100 MiB 的 ZIP 按原名同步至 `main/openvam/`。同名而内容不同的新版使用带批次号或版本号的文件名。同步可在 Actions 中通过同一标签重试。大包直接交付 Release 附件链接。

使用云端代理或 GitHub 连接器交付时，从 GitHub 再读取 `main` 的目录条目，核对大小与本地 `git hash-object --no-filters` 的值。Release 附件按远端大小和 SHA-256 核对。核验通过后，向用户给出文件下载链接、字节数和 SHA-256。已有目的地授权沿用至本流程；遇到网络中断先检查远端是否已收到，再重试。两种传输都不可用时保留原包，并说明具体阻塞位置。
