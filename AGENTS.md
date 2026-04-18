# openai-cpa 本地使用说明

这份文档写给在本项目根目录直接操作的人用。

详细的一键复制命令已经整理到根目录的 [常用命令.md](常用命令.md)，默认你使用的是 macOS / zsh，并且项目目录固定为：

```bash
/Users/meilinwang/Projects/openai-cpa-Public
```

## 访问地址和密码

Web 控制台地址：

```text
http://127.0.0.1:8000
```

默认登录密码：

```text
admin
```

本地配置文件：

```text
/Users/meilinwang/Projects/openai-cpa-Public/data/config.yaml
```

## 当前 Git / 分支开发规范

当前仓库已经按“官方上游 + 个人 fork + 本地定制分支”的方式整理好，默认约定如下：

- `upstream`：官方仓库 `https://github.com/wenfxl/openai-cpa.git`
- `origin`：你自己的 fork `https://github.com/LeoW-tech/openai-cpa.git`
- `main`：当前正式使用中的本地主开发分支，也是本地 Docker 镜像默认应基于的代码
- `upstream-main`：专门镜像官方 `upstream/main` 的观察分支，只用于对齐和观察官方开发进度

日常开发建议：

- 平时统一在 `main` 上继续改，或从 `main` 切功能分支，例如 `feat/xxx` 或 `fix/xxx`
- 不要直接在 `upstream-main` 上开发，它只用于观察和同步官方进度
- 不要直接在 `upstream/main` 上开发
- `origin/main` 与本地 `main` 保持一致，作为你 fork 上的正式主线
- `origin/upstream-main` 与本地 `upstream-main` 保持一致，作为官方观察线

## 数据和配置位置

运行时数据目录：

```text
/Users/meilinwang/Projects/openai-cpa-Public/data
```

常见内容：

- `data/config.yaml`：主配置文件
- `data/data.db`：本地 SQLite 数据库
- `data/logs/app.log`：源码方式运行时的本地日志

## 常用命令文档

文档里的所有常用命令已经独立迁移到根目录的 [常用命令.md](常用命令.md)。

新文档中的命令已经统一修订为“带项目运行目录、整行可复制执行”的单行命令，直接复制到终端即可使用。

## 当前默认约定

- Web 地址固定用 `http://127.0.0.1:8000`
- 默认密码先用 `admin`
- 主要维护方式优先使用本地 Docker 容器 `openai-cpa-local`
- 配置文件统一改 `data/config.yaml`
- 当前默认开发分支是 `main`
- 官方更新一律从 `upstream/main` 拉，本地观察分支统一使用 `upstream-main`
- 日常推送优先推到你自己的 fork，也就是 `origin`
- 所有命令都默认从项目根目录执行
