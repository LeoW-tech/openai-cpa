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
cd /Users/meilinwang/Projects/openai-cpa-Public && curl -I http://127.0.0.1:8000
```

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

## 当前默认约定

- Web 地址固定用 `http://127.0.0.1:8000`
- 默认密码先用 `admin`
- 主要维护方式优先使用本地 Docker 容器 `openai-cpa-local`
- 配置文件统一改 `data/config.yaml`
- 所有命令都默认从项目根目录执行
