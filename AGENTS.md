# OpenVam 图文交付

本仓库接收图文制作任务的最终 ZIP。云端批次使用已配置的 `deliveries` 环境，交付目的地为私有仓库 `bao270026-sys/deliveries`。用户指定其他交付方式时按当次要求执行。

- 在持有成品的制作任务内完成打包和上传。如果从默认环境启动，先用已连接的 GitHub 在同一任务检出本仓库，再继续使用现有成品。尚未取得成品时，按用户指定的文件名和资料库文件识别原件。
- 完成批次校验后使用制作流程产生的完整 ZIP。OpenVam 生图技能先执行 `render_tasks.py finalize`，再用同一版技能的 `recovery.py delivery --root <批次目录> --output <批次外的最终ZIP>` 打包。已有最终 ZIP 时直接使用。把本次完整 ZIP 作为唯一的交付文件。

在仓库根目录执行以下命令，把原文件名保存在 `main` 分支的 `openvam/` 下。

```sh
python3 scripts/publish_openvam.py "/path/to/完整批次.zip"
```

脚本校验 ZIP、只提交这个文件，并核对远端分支上的 Git blob。同名同内容可直接重跑。同名而内容不同的新版保留原件，给新版使用带批次号或版本号的文件名后重试。

单包超过 100 MiB，或当前 Git 传输受限而本机已有获准的 GitHub CLI 写入身份时，使用同一私库的 Releases 上传一个完整附件。该入口支持小于 2 GiB 的 ZIP。

```sh
python3 scripts/publish_openvam_release.py "/path/to/完整批次.zip"
```

若制作环境已有能访问本私库的 GitHub 网页登录态，也可在 Releases 新建发布并上传完整 ZIP。标签使用 `openvam-<ZIP 的 64 位小写 SHA-256>`，目标选择 `main`。正文单独写一行 `原始文件名：<原文件名.zip>`。附件上传完成后发布。

仓库工作流 `Publish OpenVam release ZIP` 会核对发布附件的 SHA-256，将不超过 100 MiB 的 ZIP 按原名同步至 `main/openvam/`。同步可在 Actions 中通过同一标签重试。超过该大小时直接使用 Release 的完整附件。

使用云端代理或 GitHub 连接器交付时，从 GitHub 再读取 `main` 的目录条目，核对大小与本地 `git hash-object --no-filters` 的值。Release 附件按远端大小和 SHA-256 核对。核验通过后，向用户给出文件下载链接、字节数和 SHA-256。已有目的地授权沿用至本流程；遇到网络中断先检查远端是否已收到，再重试。两种传输都不可用时保留原包，并说明具体阻塞位置。
