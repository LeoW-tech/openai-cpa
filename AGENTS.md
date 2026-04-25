# openai-cpa 本地使用说明

这份文档写给在本项目相关目录直接操作的人用。

详细的一键复制命令已经整理到根目录的 [常用命令.md](常用命令.md)。当前这个项目同时存在 `mac` 本地环境和 `Linux` 正式环境，两端都在运行，所有操作前都必须先确认自己要操作的是哪一端，避免把一端的命令误打到另一端。

## 双端运行声明

当前存在两套并行运行环境：

| 项目 | mac 本地环境 | Linux 正式环境 |
| --- | --- | --- |
| 部署根目录 | `/Users/meilinwang/Projects/openai-cpa-Public` | `/srv/openai-cpa` |
| 仓库目录 | `/Users/meilinwang/Projects/openai-cpa-Public` | `/srv/openai-cpa/repo` |
| 数据目录 | `/Users/meilinwang/Projects/openai-cpa-Public/data` | `/srv/openai-cpa/data` |
| 配置文件 | `/Users/meilinwang/Projects/openai-cpa-Public/data/config.yaml` | `/srv/openai-cpa/data/config.yaml` |
| 容器名 | `openai-cpa-local` | `openai-cpa` |
| 主要运行入口 | 本地项目目录 + 本地容器脚本 | `/srv/openai-cpa/docker-compose.linux.yml` |

重要约定：

- `mac` 侧以本地项目目录和 `openai-cpa-local` 相关命令为主。
- `Linux` 侧以 `/srv/openai-cpa/docker-compose.linux.yml` 和容器 `openai-cpa` 为主。
- 排障、改配置、重启服务、重建部署前，先确认目标数据目录和目标容器名。
- 不要把 `mac` 的 `data/config.yaml` 和 `Linux` 的 `/srv/openai-cpa/data/config.yaml` 混用。

## 独立运行边界

- `mac` 的 `openai-cpa-local` 和 `Linux` 的 `openai-cpa` 是两套独立实例，必须各自维护自己的 `data/`、`data.db`、日志和容器，不要把两端当成同一个运行面。
- 这份仓库当前允许两端**共同指向 Linux 那台 `sub2api`**，也就是 `http://192.168.31.214:8080/`；这是设计上的共享数据面，不是把 openai-cpa 主进程合并成一套。
- 除非用户明确要求搭建一套新的本机 `sub2api`，否则不要把这份仓库里的 `sub2api_mode.api_url` 改成 `127.0.0.1:8080`，也不要用它去替换 Linux 那套服务。
- `cluster_master_url` 才是 openai-cpa 控制台之间发生跨机互控/互看日志的开关；如果目标是独立运行，默认应保持为空，只有做 cluster 联动时才显式填写。
- 判断“是否真共享任务状态”时，优先对比各自机器上的 `registration_runs`、`registration_attempt_events` 和实际 `data/data.db`，不要只看日志文案是否相似。

## 访问地址和密码

Web 控制台地址对照：

| 环境 | 地址 |
| --- | --- |
| mac 本机访问 | `http://127.0.0.1:8000` |
| Linux 本机访问 | `http://127.0.0.1:8000` |
| Linux 局域网访问 | `http://192.168.31.214:8000` |

默认登录密码：

```text
admin
```

## 当前 Git / 分支开发规范

当前仓库已经按“官方上游 + 个人 fork + 本地定制分支”的方式整理好，默认约定如下：

- `upstream`：官方仓库 `https://github.com/wenfxl/openai-cpa.git`
- `origin`：你自己的 fork `https://github.com/LeoW-tech/openai-cpa.git`
- `main`：当前正式使用中的本地主开发分支
- `upstream-main`：专门镜像官方 `upstream/main` 的观察分支，只用于对齐和观察官方开发进度

日常开发建议：

- 平时统一在 `main` 上继续改，或从 `main` 切功能分支，例如 `feat/xxx` 或 `fix/xxx`
- 不要直接在 `upstream-main` 上开发，它只用于观察和同步官方进度
- 不要直接在 `upstream/main` 上开发
- `origin/main` 与本地 `main` 保持一致，作为你 fork 上的正式主线
- `origin/upstream-main` 与本地 `upstream-main` 保持一致，作为官方观察线

两端 Git 约定相同，但执行目录不同：

- `mac` 版 Git 命令默认在 `/Users/meilinwang/Projects/openai-cpa-Public`
- `Linux` 版 Git 命令默认在 `/srv/openai-cpa/repo`

## 冲突处理原则

- 适用范围包括 `main` 与 `upstream-main` 的同步合并
- 本地已有且仍需保留的定制功能，如果上游本次更新没有覆盖该能力，冲突时优先保留本地定制。
- 如果本地定制对应的能力，上游本次更新已经实现、吸收或以新的结构重构覆盖，冲突时以上游实现为准，再按需重新评估是否补回少量仍然必要的本地差异。
- 如果无法明确判断两边是否属于同一能力，或无法确认取舍后是否会影响当前运行面与既有行为，就停止自动处理，保留冲突点，等待人工裁定。

## 运行态与配置位置对照

### mac 本地环境

- 仓库目录：`/Users/meilinwang/Projects/openai-cpa-Public`
- 数据目录：`/Users/meilinwang/Projects/openai-cpa-Public/data`
- 主配置文件：`/Users/meilinwang/Projects/openai-cpa-Public/data/config.yaml`
- 本地 SQLite：`/Users/meilinwang/Projects/openai-cpa-Public/data/data.db`
- 源码方式日志：`/Users/meilinwang/Projects/openai-cpa-Public/data/logs/app.log`

### Linux 正式环境

- 部署根目录：`/srv/openai-cpa`
- 仓库目录：`/srv/openai-cpa/repo`
- 数据目录：`/srv/openai-cpa/data`
- 主配置文件：`/srv/openai-cpa/data/config.yaml`
- 本地 SQLite：`/srv/openai-cpa/data/data.db`
- compose 文件：`/srv/openai-cpa/docker-compose.linux.yml`

## 容器名与运行入口对照

### mac 本地环境

- 容器名：`openai-cpa-local`
- 推荐重启入口：`./scripts/restart_local_container.sh`
- 推荐重建入口：`./scripts/rebuild_local_container.sh`

### Linux 正式环境

- 容器名：`openai-cpa`
- 推荐重启入口：`docker compose -f /srv/openai-cpa/docker-compose.linux.yml restart openai-cpa`
- 推荐重建入口：`docker compose -f /srv/openai-cpa/docker-compose.linux.yml up -d --build`

## 常用命令文档

文档里的所有常用命令已经独立迁移到根目录的 [常用命令.md](常用命令.md)。

新文档里的命令统一遵守以下规则：

- 看到 `Linux 版` 只在 Linux 上执行
- 看到 `mac 版` 只在 mac 上执行
- 没标环境且命令完全一致时，表示两端通用
- 所有命令都保持“带真实路径、整行可复制执行”的风格

## 当前默认约定

- 当前是双端并列运行，不设单一默认主端
- `mac` 环境优先按本地项目目录和 `openai-cpa-local` 相关脚本维护
- `Linux` 环境优先按 `/srv/openai-cpa` 和 `docker-compose.linux.yml` 维护
- 配置文件统一在各自真实数据目录中修改
- 当前默认开发分支是 `main`
- 官方更新一律从 `upstream/main` 拉，本地观察分支统一使用 `upstream-main`
- 日常推送优先推到你自己的 fork，也就是 `origin`
