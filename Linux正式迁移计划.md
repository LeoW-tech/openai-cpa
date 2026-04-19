# openai-cpa + Sub2API Linux 正式迁移计划

> 本文是 `openai-cpa` 从当前 mac 本地运行环境迁移到局域网 Linux 节点的正式执行手册。本文同时服务于三类角色：
>
> - `A`：mac 机器上的 AI
> - `B`：人类
> - `C`：Linux 机器上的 AI
>
> 本文不是概要说明，而是一份按阶段执行的正式迁移手册。执行时必须遵守以下规则：
>
> - 所有阶段按角色拆分，不混合角色。
> - 能由 `A` 或 `C` 完成的动作，不分配给 `B`。
> - `B` 只负责不可替代的人类授权、停机确认和最终外部验收。
> - `sub2api` 迁移先行，`openai-cpa` 迁移后置。
> - `openai-cpa` 首发只做局域网访问，不在本次迁移内扩展公网入口。

## 1. 目标与范围

本计划的目标是：

- 先完成 `sub2api` 迁移到 Linux
- 再把当前 `openai-cpa` 迁移到同一台 Linux
- 保留 `openai-cpa` 现有运行态数据
- 把 `openai-cpa` 的宿主机依赖收敛到 Linux 上已经真实存在的 `sub2api` 与 `clash`
- 让 Linux 成为新的正式运行节点，同时保留可回滚的 mac 基线

本计划明确不做以下事情：

- 不在本次迁移中切换到 MySQL
- 不在本次迁移中为 `openai-cpa` 增加公网访问入口
- 不继续追逐旧配置中不存在 live 提供者的 `19090` 和 `41001-41020`
- 不在本次迁移中引入 `watchtower`
- 不在本次迁移中让 `openai-cpa` 容器获得 `/var/run/docker.sock`

## 2. 锁定的技术决策

以下决策已经锁定，本次迁移不再临时改方案：

- `sub2api` 继续按现有正式迁移方案执行，计划文件为：
  `/Users/meilinwang/Projects/sub2api/Linux正式迁移计划.md`
- `openai-cpa` 正式目录固定为：`/srv/openai-cpa`
- `sub2api` 正式目录固定为：`/srv/sub2api`
- `openai-cpa` 在 Linux 上使用 Docker Compose 本地构建运行
- `openai-cpa` 使用当前仓库代码构建，不使用仓库自带 compose 里的上游 `latest` 镜像
- `openai-cpa` 继续使用 SQLite
- `openai-cpa` 对外只开放局域网入口：`http://192.168.31.214:8000`
- `sub2api` 在 Linux 上必须保持宿主机本地入口：`http://127.0.0.1:8080/`
- `openai-cpa` 容器访问宿主机依赖时统一依赖 `host.docker.internal:host-gateway`
- `openai-cpa` 迁移时以 Linux 现有 `clash.service` 的真实端口为准：
  - `http://127.0.0.1:9090`
  - `http://127.0.0.1:7890`
  - `http://127.0.0.1:7891`
- `openai-cpa` 首发按“单个 live Clash 实例 + 保守并发”运行，不假设存在多端口代理池

## 3. 当前已知环境摘要

### 3.1 mac 源端现状

- 仓库目录：`/Users/meilinwang/Projects/openai-cpa-Public`
- 当前分支：`main`
- 当前工作树：干净
- Git 远程：
  - `origin = https://github.com/LeoW-tech/openai-cpa.git`
  - `upstream = https://github.com/wenfxl/openai-cpa.git`
- 当前仓库可以由 Linux 直接 `git clone`
- 当前权威运行态位于项目根目录的 `data/`，该目录未纳入 Git

### 3.2 openai-cpa 当前必须保留的运行态

迁移时必须保留至少以下内容：

- `data/config.yaml`
- `data/data.db`
- `data/token.json`
- `data/credentials.json`
- `data/logs/`
- 其他 `data/` 下仍被当前运行态使用的文件

### 3.3 Linux 目标端现状

Linux 环境已知事实如下：

- 主机名：`lim`
- 系统：Ubuntu 22.04.5 LTS
- CPU 架构：`x86_64`
- 时区：`Asia/Shanghai`
- 局域网 IP：`192.168.31.214`
- 磁盘剩余空间：约 `523G`
- Docker：当前未安装，但 `sub2api` 迁移阶段会补齐
- GitHub：可访问
- 现有 live Clash：
  - `127.0.0.1:7890`
  - `127.0.0.1:7891`
  - `127.0.0.1:9090`
- 现有 Clash 服务文件：`/etc/systemd/system/clash.service`
- 现有 Clash 运行目录：`/home/lim/clash`

### 3.4 与旧配置冲突的已确认事实

当前 `openai-cpa` 的 `data/config.yaml` 中仍存在这些历史配置：

- `sub2api_mode.api_url = http://127.0.0.1:8080/`
- `clash_proxy_pool.api_url = http://127.0.0.1:19090`
- `default_proxy = http://127.0.0.1:41001`
- `warp_proxy_list = 127.0.0.1:41001-41020`

但补充排查结果已经确认：

- `19090` 当前没有 live 提供者
- `41001-41020` 当前没有 live 提供者
- 旧机实际存在的本地代理入口是：
  - `7890`
  - `7891`
  - `9090`

因此，本次迁移明确以 Linux 的真实 live Clash 端口为准，不再试图复刻不存在的 `19090 + 41001-41020`

## 4. 目标架构

### 4.1 首发正式架构

```text
局域网浏览器
    ↓
http://192.168.31.214:8000
    ↓
Linux 宿主机 8000 端口
    ↓
openai-cpa 容器
    ├─ 挂载 /srv/openai-cpa/data -> /app/data
    ├─ 通过 host.docker.internal 访问宿主机 sub2api
    └─ 通过 host.docker.internal 访问宿主机 clash

Linux 宿主机
    ├─ sub2api: 127.0.0.1:8080
    └─ clash: 127.0.0.1:7890 / 7891 / 9090
```

### 4.2 Linux 目录布局

```text
/srv/openai-cpa/
  repo/                    仓库代码
  data/                    迁移后的运行态目录
  backups/                 迁移包、冷备份、回滚包
  docker-compose.linux.yml Linux 正式运行编排文件
```

### 4.3 首发监听策略

- `sub2api`：保持 `127.0.0.1:8080`
- `clash`：保持宿主机现有本地监听方式
- `openai-cpa`：宿主机映射 `0.0.0.0:8000`，供局域网访问
- 不新增 `openai-cpa` 公网入口

## 5. 角色定义与边界

### 5.1 A：mac 机器上的 AI

负责内容：

- 维护本计划文件
- 校验当前仓库和运行态
- 准备 `openai-cpa` 迁移包和冷备份
- 停止 mac 侧旧实例
- 交付 Linux 侧需要的运行态文件
- 保存回滚基线

禁止内容：

- 不负责 Linux 安装 Docker
- 不负责 Linux 创建 systemd 服务
- 不负责 Linux 上的正式容器启动

### 5.2 B：人类

负责内容：

- 确认停机窗口
- 在必要时允许停止旧机服务
- 在最终阶段用浏览器做人类验收
- 如 `sub2api` 原计划要求人类授权，则在第一阶段完成对应授权

禁止内容：

- 不手工 SSH 上去改 Linux 配置
- 不手工编写 compose
- 不手工修改 `config.yaml`
- 不手工搬运目录，除非 AI 确实无法直接完成

### 5.3 C：Linux 机器上的 AI

负责内容：

- 先按 `sub2api` 计划完成第一阶段迁移
- 创建 `/srv/openai-cpa` 目录结构
- 拉取仓库代码
- 恢复运行态数据
- 创建 Linux 专用 compose 文件
- 修改 Linux 专用 `config.yaml`
- 启动并验证 `openai-cpa`
- 在失败时执行 Linux 侧备份和停机动作

禁止内容：

- 不擅自改变迁移架构
- 不擅自切换成 MySQL
- 不擅自继续追逐 `19090` 与 `41001-41020`
- 不擅自给 `openai-cpa` 增加公网入口

## 6. 前置条件清单

### 6.1 开始前必须确认的输入

- `sub2api` 迁移计划文件已存在且作为第一阶段正式基线
- Linux 可访问 GitHub
- Linux 上 `sub2api` 将运行在 `127.0.0.1:8080`
- Linux 上 `clash.service` 可继续复用
- 已预留停机窗口用于切换 `openai-cpa`

### 6.2 openai-cpa 必须准备的交付物

- 当前仓库 Git 远程信息
- 当前分支信息
- 当前工作树状态
- `data/` 冷备份
- `data/` 内关键文件校验信息

### 6.3 本次必须避免的事项

- 不把整个工作树当成运行态交付物
- 不使用仓库默认 `docker-compose.yml` 直接上线
- 不使用 `docker-compose2.yml`
- 不挂载 `docker.sock`
- 不启用 `watchtower`
- 不在 `sub2api` 未验证前启动 `openai-cpa`

## 7. 分阶段迁移步骤

---

## Phase 0：冻结前提与执行边界

### 完成条件

- `sub2api` 迁移先行这件事已锁定
- `openai-cpa` 只做局域网访问这件事已锁定
- Linux 正式目录已锁定为 `/srv/openai-cpa`
- 所有角色都知道：本次不追逐不存在的 `19090/41001-41020` 端口池，而是用 Linux 现有 Clash live 端口

### A：mac 机器上的 AI

1. 把本文作为 `openai-cpa` 迁移唯一正式手册。
2. 明确 `sub2api` 第一阶段执行基线为：
   `/Users/meilinwang/Projects/sub2api/Linux正式迁移计划.md`
3. 记录当前仓库状态：
   - 分支：`main`
   - 工作树：干净
   - 代码来源：Linux 可直接 `git clone`
4. 记录当前权威运行态在 `data/`，不在 Git 中。

### B：人类

1. 不需要参与本阶段配置动作。
2. 仅需知晓后续最终验收地址将是 `http://192.168.31.214:8000`。

### C：Linux 机器上的 AI

1. 预留 `/srv/openai-cpa` 作为正式目录。
2. 不提前创建 `openai-cpa` 容器。
3. 不抢先改 Clash。
4. 不在 `sub2api` 未就绪前启动第二阶段。

---

## Phase 1：先完成 Sub2API 迁移

### 完成条件

- `/Users/meilinwang/Projects/sub2api/Linux正式迁移计划.md` 已执行完毕
- Linux 上 `sub2api` 健康入口 `http://127.0.0.1:8080/health` 正常
- 如果 `door-gateway` 是原计划的一部分，则它也已健康运行
- Docker Engine 与 Compose v2 已在 Linux 上安装可用

### A：mac 机器上的 AI

1. 不在本计划里重做 `sub2api` 方案设计。
2. 仅将现有 `sub2api` 正式迁移计划文件交给 `C` 执行。
3. 等待 `C` 返回以下最低验收事实：
   - `docker version` 可用
   - `docker compose version` 可用
   - `curl -fsS http://127.0.0.1:8080/health` 成功

### B：人类

1. 仅当 `sub2api` 原计划要求 Cloudflare 或外部账号授权时再介入。
2. 如果 `sub2api` 原计划不需要你手动登录授权，则本阶段无需动作。

### C：Linux 机器上的 AI

1. 严格按 `/Users/meilinwang/Projects/sub2api/Linux正式迁移计划.md` 执行。
2. 完成后向 `A` 明确回报：
   - `sub2api` 宿主机绑定方式
   - `sub2api` 健康检查结果
   - `door-gateway` 是否已就绪
   - Docker / Compose 是否已可复用给 `openai-cpa`

---

## Phase 2：导出 openai-cpa 运行态并准备 Linux 目录

### 完成条件

- mac 上 `openai-cpa` 运行态已完成备份
- Linux 上 `/srv/openai-cpa` 目录树已创建
- Linux 上代码已从 GitHub 拉下
- Linux 上 `data/` 已从 mac 迁入，但尚未开始正式流量切换

### A：mac 机器上的 AI

1. 生成迁移前备份清单，至少包含：
   - `data/config.yaml`
   - `data/data.db`
   - `data/token.json`
   - `data/credentials.json`
   - `data/logs/`
2. 做一次热备份：
   - 打包 `data/` 到时间戳归档
   - 生成校验信息
3. 在正式切换窗口前，停止 mac 上当前运行的 `openai-cpa` 进程或容器。
4. 停止后立刻做一次最终冷备份：
   - 再次打包 `data/`
   - 这份包作为 Linux 恢复和回滚基线
5. 不把整个仓库工作树打包给 Linux。

### B：人类

1. 本阶段无需手工拷文件。
2. 仅需在安排好的停机窗口内允许 `A` 停止旧机上的当前运行实例。

### C：Linux 机器上的 AI

1. 创建目录树：

```bash
sudo mkdir -p /srv/openai-cpa/repo
sudo mkdir -p /srv/openai-cpa/data
sudo mkdir -p /srv/openai-cpa/backups
sudo chown -R lim:lim /srv/openai-cpa
```

2. 从 `origin/main` 克隆仓库代码到 `/srv/openai-cpa/repo`。
3. 接收 `A` 交付的最终 `data/` 冷备份并恢复到 `/srv/openai-cpa/data`。
4. 不恢复 `.venv`、`.pytest_cache`、`__pycache__` 等本地缓存。
5. 恢复完成后，确认以下文件存在：
   - `/srv/openai-cpa/data/config.yaml`
   - `/srv/openai-cpa/data/data.db`

---

## Phase 3：生成 Linux 专用运行配置并启动 openai-cpa

### 完成条件

- Linux 专用 Compose 文件已创建
- `config.yaml` 已按 Linux 实际环境改好
- `openai-cpa` 已成功启动
- `openai-cpa` 能从容器内访问宿主机上的 `sub2api` 和 `clash`

### A：mac 机器上的 AI

1. 作为配置参考，向 `C` 明确以下迁移意图：
   - 保留 `database.type = sqlite`
   - 保留 `sub2api_mode.api_url = http://127.0.0.1:8080/`
   - 不继续依赖 `19090` 与 `41001-41020`
   - 首发使用 Linux live Clash 端口 `9090/7890/7891`
2. 明确 Linux 首发并发策略：
   - `enable_multi_thread_reg = true`
   - `reg_threads = 5`
3. 明确本次首发不启用 `watchtower`。
4. 明确本次首发不把 `docker.sock` 暴露给 `openai-cpa` 容器。

### B：人类

1. 本阶段无需手工改文件。
2. 不手工 SSH 上去改 `config.yaml` 或 Compose 文件。

### C：Linux 机器上的 AI

1. 在 `/srv/openai-cpa` 新建正式运行文件 `docker-compose.linux.yml`，要求如下：
   - `build.context = ./repo`
   - 使用 `./repo/Dockerfile`
   - 端口映射 `8000:8000`
   - 挂载 `./data:/app/data`
   - 配置 `extra_hosts: ["host.docker.internal:host-gateway"]`
   - 不包含 `watchtower`
   - 不挂载 `/var/run/docker.sock`
   - `restart: unless-stopped`

2. 编辑 `/srv/openai-cpa/data/config.yaml`，按 Linux 实际环境修正为：
   - `database.type = sqlite`
   - `sub2api_mode.enable = true`
   - `sub2api_mode.api_url = http://127.0.0.1:8080/`
   - `default_proxy = http://127.0.0.1:7890`
   - `clash_proxy_pool.enable = true`
   - `clash_proxy_pool.pool_mode = false`
   - `clash_proxy_pool.api_url = http://127.0.0.1:9090`
   - `clash_proxy_pool.test_proxy_url = http://127.0.0.1:7890`
   - `warp_proxy_list = []`
   - `reg_threads = 5`

3. 同时把 `clash_proxy_pool.secret` 和 `clash_proxy_pool.group_name` 与 Linux 宿主机真实 Clash 配置对齐：
   - 读取 `/home/lim/clash/config.yaml`
   - 如果该文件有 `secret`，就同步到 `config.yaml`
   - 如果该文件没有 `secret`，就把 `clash_proxy_pool.secret` 置空
   - `group_name` 以 Linux 实际策略组名为准，不沿用错误历史值

4. 保留 `web_password` 当前值，不在迁移时顺手重置。

5. 用新编排文件启动服务：

```bash
cd /srv/openai-cpa
docker compose -f docker-compose.linux.yml up -d --build
```

6. 启动后先只做健康验证，不马上开始真实注册任务。

---

## Phase 4：验证 openai-cpa 与 Sub2API / Clash 联通

### 完成条件

- `openai-cpa` Web 页面可访问
- 登录 API 可成功拿到 token
- `sub2api` 组列表接口可从 `openai-cpa` 访问成功
- `openai-cpa` 容器日志中没有明显的 `host.docker.internal`、`sub2api`、`clash` 连接错误
- 人工验收通过

### A：mac 机器上的 AI

1. 接收 `C` 回传的验证结果。
2. 如果 `C` 在联通性验证阶段失败，则保持 mac 源端不销毁，准备随时回滚。
3. 在 `C` 未明确通过验收前，不把旧机数据标记为废弃。

### B：人类

1. 仅在 `C` 报告自动验证通过后，打开浏览器访问：
   - `http://192.168.31.214:8000`
2. 用当前 `web_password` 登录。
3. 只做界面可用性确认，不手工改配置。
4. 重点看三件事：
   - 首页能正常打开
   - 登录后仪表盘正常显示
   - 与 `Sub2API` 相关的页面或配置项没有立刻报错

### C：Linux 机器上的 AI

1. 验证首页 HTML 可访问：

```bash
curl -fsS http://127.0.0.1:8000/ > /tmp/openai-cpa-index.html
```

2. 验证登录接口可用：

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"password":"<当前web_password>"}'
```

3. 从登录响应里取 token，再验证状态接口：

```bash
curl -fsS "http://127.0.0.1:8000/api/status?token=<token>"
```

4. 用同一个 token 验证 `Sub2API` 联通：

```bash
curl -fsS "http://127.0.0.1:8000/api/sub2api/groups?token=<token>"
```

5. 直接验证宿主机 `sub2api` 健康：

```bash
curl -fsS http://127.0.0.1:8080/health
```

6. 检查 `openai-cpa` 日志末尾，确认没有明显连接错误：

```bash
cd /srv/openai-cpa
docker compose -f docker-compose.linux.yml logs --tail 200
```

7. 检查 8000 监听和容器状态：

```bash
ss -lntp | grep ':8000'
docker ps
```

8. 如果以上都成功，再把结果交给 `B` 做最终肉眼验收。

---

## Phase 5：切换完成与回滚策略

### 完成条件

- Linux 成为唯一正式运行点
- mac 保留可回滚备份
- 回滚条件与动作被写清楚

### A：mac 机器上的 AI

1. 在 Linux 验收通过前，不删除 mac 上的旧运行目录和最终冷备份。
2. 记录回滚入口：
   - 如果 Linux 在未开始真实任务前失败，直接恢复 mac 上旧服务
   - 如果 Linux 在已开始真实任务后失败，先把 Linux 上最新 `data/` 回传保存，再决定是否回滚
3. 至少保留一份 mac 端最终冷备份，直到人工确认 Linux 稳定运行。

### B：人类

1. 仅在确认 Linux 侧稳定运行一段时间后，才允许清理旧机。
2. 如果验收后发现页面可打开但业务异常，不要自己改 Linux 配置，直接让 `C` 处理或触发回滚。

### C：Linux 机器上的 AI

1. 如果失败发生在容器启动前或健康检查前，停止 Linux 容器并等待 `A` 恢复旧机。
2. 如果失败发生在已接管运行态但尚未开始真实注册任务，停止 Linux 容器即可，mac 冷备份仍然是最新权威状态。
3. 如果失败发生在 Linux 已开始真实注册任务之后，先打包 `/srv/openai-cpa/data` 到 `/srv/openai-cpa/backups/`，再决定是否回传给 `A`。
4. 不要在失败时直接覆盖或删除 mac 侧原始备份。

## 8. 验收清单

必须通过的测试场景如下：

- `sub2api` 已先行迁移完成，并且 `http://127.0.0.1:8080/health` 返回成功
- `openai-cpa` Linux 容器能启动并监听 `8000`
- `GET /` 返回控制台 HTML，而不是 404
- `POST /api/login` 使用当前 `web_password` 可获得 token
- `GET /api/status` 能在带 token 情况下返回状态
- `GET /api/sub2api/groups` 能通过 `openai-cpa` 正常访问 Linux 本机 `sub2api`
- `openai-cpa` 日志中没有持续的 `host.docker.internal` 解析失败、`sub2api` 连接失败、`Clash API` 连接失败
- 人工浏览器验收能正常打开 `http://192.168.31.214:8000`

## 9. 默认假设

- 本计划默认继续使用现有的 `sub2api` 正式迁移计划文件，不在本文里复制它的全部细节。
- 本计划默认 `openai-cpa` 首发只需要局域网访问，不需要公网入口。
- 本计划默认 Linux 上 `clash.service` 会继续存在并由 `C` 复用。
- 本计划默认旧机补充排查结果可信：`19090` 和 `41001-41020` 当前不是 live 依赖，因此本次迁移不以复刻它们为成功前提。
- 本计划默认 `openai-cpa` 首发使用“单个 live Clash 实例 + 保守并发”，而不是继续假设多端口代理池存在。
- 本计划默认 Linux 可访问 GitHub，因此代码获取使用 `git clone`，运行态获取使用 `data/` 冷备份恢复。
- 本计划默认 `docker-compose2.yml` 不纳入本次迁移，因为 Linux 目标机没有 MySQL，当前项目也实际使用 SQLite。

## 10. Linux 侧执行顺序摘要

如果你把本文直接发给 Linux 侧 AI，它应按以下顺序执行：

1. 先执行 `/Users/meilinwang/Projects/sub2api/Linux正式迁移计划.md`
2. 验证 `sub2api` 健康
3. 创建 `/srv/openai-cpa`
4. `git clone` 当前仓库到 `/srv/openai-cpa/repo`
5. 从 mac 恢复 `data/` 到 `/srv/openai-cpa/data`
6. 生成 `docker-compose.linux.yml`
7. 按本文修订 Linux 专用 `config.yaml`
8. 启动 `openai-cpa`
9. 做 API 联通验证
10. 交给人类做最终浏览器验收
