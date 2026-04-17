# openai-cpa 本地使用说明

这份文档写给在本项目根目录直接操作的人用。

所有命令都按“可整行复制到终端直接执行”来写，默认你使用的是 macOS / zsh，并且项目目录固定为：

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
- `upgrade/v10.1.5-custom`：当前正式使用中的定制开发分支，也是本地 Docker 镜像默认应基于的代码
- `backup/pre-v10.1.5-local`：升级前的本地备份分支，只保留做兜底，不作为日常开发分支

日常开发建议：

- 平时优先在 `upgrade/v10.1.5-custom` 上继续改
- 如果一次改动比较大，建议从 `upgrade/v10.1.5-custom` 再切一个功能分支，例如 `feat/xxx` 或 `fix/xxx`
- 不要在 `backup/pre-v10.1.5-local` 上继续开发
- 不要直接在 `upstream/main` 上开发
- `origin/main` 暂时视为你 fork 上的干净主线，不作为当前定制版的日常开发入口

## 最常用 Git 命令

### 1. 查看当前所在分支、跟踪关系和远程地址

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git status --short --branch && git branch -vv && git remote -v
```

### 2. 切回当前定制开发分支

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git checkout upgrade/v10.1.5-custom
```

### 3. 从当前定制分支新建一个功能分支

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git checkout upgrade/v10.1.5-custom && git pull --ff-only origin upgrade/v10.1.5-custom && git checkout -b feat/my-change
```

### 4. 查看官方最新提交和标签

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git fetch upstream --tags && git log --oneline --decorate upstream/main -5 && git tag --sort=-version:refname | head
```

### 5. 把当前改动提交到本地 git

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git add -A && git commit -m "feat: describe your change"
```

### 6. 推送当前分支到自己的 GitHub fork

注意：本项目当前推送前会触发 `pytest` 检查，显式补上 `PYTHONPATH=.` 最稳妥。

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && PYTHONPATH=. git push -u origin HEAD
```

### 7. 本地先跑测试再提交 / 推送

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && PYTHONPATH=. pytest
```

### 8. 以后同步官方最新版时的推荐起手式

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git checkout upgrade/v10.1.5-custom && git fetch upstream --tags && git log --oneline --decorate --left-right HEAD...upstream/main
```

## 最常用命令

### 1. 查看当前容器是否在运行

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker ps --filter name=openai-cpa-local --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

### 2. 查看 Web 控制台日志

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker logs -f openai-cpa-local
```

### 3. 停止当前容器

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker stop openai-cpa-local
```

### 4. 启动已存在的容器

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker start openai-cpa-local
```

### 5. 重启容器

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker restart openai-cpa-local
```

### 6. 进入容器内部

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker exec -it openai-cpa-local /bin/bash
```

### 7. 查看当前配置文件前 200 行

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && sed -n '1,200p' data/config.yaml
```

### 8. 直接用系统文本编辑器打开配置文件

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && open -e data/config.yaml
```

### 9. 查看 8000 端口是否已经监听

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && lsof -nP -iTCP:8000 -sTCP:LISTEN
```

### 10. 测试首页是否可访问

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && curl -sS -o /tmp/openai-cpa-home.html -w '%{http_code}\n' http://127.0.0.1:8000 && wc -c /tmp/openai-cpa-home.html
```

说明：本项目首页对 `HEAD` 请求会返回 `405`，所以这里统一用 `GET` 检查服务可访问性。

## 一键重建本地 Docker 部署

下面这条命令会直接删除旧容器、重新构建本地镜像、并重新启动容器。

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker rm -f openai-cpa-local >/dev/null 2>&1 || true && docker build -t openai-cpa-local:latest . && docker run -d --name openai-cpa-local -p 8000:8000 -v /Users/meilinwang/Projects/openai-cpa-Public/data:/app/data -v /var/run/docker.sock:/var/run/docker.sock --add-host=host.docker.internal:host-gateway openai-cpa-local:latest
```

如果你只是想重建镜像但暂时不启动容器，用这条：

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker build -t openai-cpa-local:latest .
```

如果你只想重新创建容器，不重新构建镜像，用这条：

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker rm -f openai-cpa-local >/dev/null 2>&1 || true && docker run -d --name openai-cpa-local -p 8000:8000 -v /Users/meilinwang/Projects/openai-cpa-Public/data:/app/data -v /var/run/docker.sock:/var/run/docker.sock --add-host=host.docker.internal:host-gateway openai-cpa-local:latest
```

## 源码方式启动

如果你不想走 Docker，也可以直接在本机跑 Python。

### 1. 创建虚拟环境并安装依赖

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

### 2. 前台启动服务

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && source .venv/bin/activate && python wfxl_openai_regst.py
```

### 3. 后台启动服务并写入日志

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && mkdir -p data/logs && source .venv/bin/activate && nohup python wfxl_openai_regst.py > data/logs/app.log 2>&1 & echo $!
```

### 4. 查看源码方式日志

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && tail -f data/logs/app.log
```

## 数据和配置位置

运行时数据目录：

```text
/Users/meilinwang/Projects/openai-cpa-Public/data
```

常见内容：

- `data/config.yaml`：主配置文件
- `data/data.db`：本地 SQLite 数据库
- `data/logs/app.log`：源码方式运行时的本地日志

## 推荐排错命令

### 1. 看容器最后 100 行日志

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker logs --tail 100 openai-cpa-local
```

### 2. 查看容器详细信息

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker inspect openai-cpa-local
```

### 3. 看项目当前 git 状态

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git status
```

### 4. 看最近 5 条提交

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git log --oneline -5
```

### 5. 看当前分支和远程分支差异

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git fetch --all --tags && git log --oneline --decorate --left-right HEAD...origin/$(git branch --show-current)
```

### 6. 看当前运行中的本地镜像版本和容器状态

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && docker ps --filter name=openai-cpa-local --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' && docker images openai-cpa-local
```

## 常用开发 / 部署命令

### 1. 在当前定制分支上一键重建并启动本地 Docker

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git checkout upgrade/v10.1.5-custom && docker rm -f openai-cpa-local >/dev/null 2>&1 || true && docker build -t openai-cpa-local:latest . && docker run -d --name openai-cpa-local -p 8000:8000 -v /Users/meilinwang/Projects/openai-cpa-Public/data:/app/data -v /var/run/docker.sock:/var/run/docker.sock --add-host=host.docker.internal:host-gateway openai-cpa-local:latest
```

### 2. 修改代码后，一键测试 + 提交 + 推送当前分支

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && PYTHONPATH=. pytest && git add -A && git commit -m "feat: describe your change" && PYTHONPATH=. git push -u origin HEAD
```

### 3. 从当前定制分支切一个修复分支并启动本地开发

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git checkout upgrade/v10.1.5-custom && git pull --ff-only origin upgrade/v10.1.5-custom && git checkout -b fix/my-change && docker rm -f openai-cpa-local >/dev/null 2>&1 || true && docker build -t openai-cpa-local:latest . && docker run -d --name openai-cpa-local -p 8000:8000 -v /Users/meilinwang/Projects/openai-cpa-Public/data:/app/data -v /var/run/docker.sock:/var/run/docker.sock --add-host=host.docker.internal:host-gateway openai-cpa-local:latest
```

## 提交本地 git

更新文档、配置说明或代码后，优先在项目根目录执行：

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git status
```

如果只是提交本次文档更新，可以直接用：

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git add AGENTS.md .gitignore && git commit -m "docs: add local operations guide"
```

如果你要提交的是其他改动，请先用：

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && git add -A && git commit -m "feat: update local deployment workflow"
```

如果你还要顺手推送到自己的 fork，推荐直接用：

```bash
cd /Users/meilinwang/Projects/openai-cpa-Public && PYTHONPATH=. pytest && git add -A && git commit -m "feat: describe your change" && PYTHONPATH=. git push -u origin HEAD
```

## 当前默认约定

- Web 地址固定用 `http://127.0.0.1:8000`
- 默认密码先用 `admin`
- 主要维护方式优先使用本地 Docker 容器 `openai-cpa-local`
- 配置文件统一改 `data/config.yaml`
- 当前默认开发分支是 `upgrade/v10.1.5-custom`
- 官方更新一律从 `upstream` 拉，不直接拿 `origin/main` 当官方基线
- 日常推送优先推到你自己的 fork，也就是 `origin`
- 所有命令都默认从项目根目录执行
