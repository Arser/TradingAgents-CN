# Docker Compose 源码部署

本指南适用于 Linux 上的全新安装。需安装 Git、Docker Engine、Docker Compose v2 和 OpenSSL，
当前用户需有 Docker 操作权限。主机需要能访问容器镜像、Python 和 npm 软件仓库。

## 获取代码并初始化

```bash
git clone --branch v3.0 https://github.com/Arser/TradingAgents-CN.git
cd TradingAgents-CN
./docker/init.sh
```

初始化脚本从 `docker/.env.example` 生成本机 `.env`，为数据库、Redis、JWT、CSRF 和初始管理员
生成随机密码/密钥，同时生成 SearXNG 配置、MongoDB keyfile 和持久化目录。重复执行会保留已有配置。

按需编辑 `.env`。初始管理员用户名为 `admin`，密码是 `.env` 中的 `ADMIN_DEFAULT_PASSWORD`；
该值仅用于空数据库首次建号。MongoDB、Redis 使用 Compose 服务名 `mongodb`、`redis` 连接，
SearXNG 使用 `http://searxng:8080`。可参考根目录 `.env.example` 配置其他选项。

## 构建并启动

```bash
./docker/rebuild.sh
docker compose ps
curl -fsS http://127.0.0.1:8082/api/health
```

访问 `http://服务器地址:8082`，使用初始管理员账号登录。在系统设置中配置模型供应商及 API Key、
默认模型、Embedding 模型和数据源，并同步股票/ETF 基础数据后开始研究。

Compose 启动六个服务：MongoDB、Redis、后端、前端、Nginx 和 SearXNG。只有 Nginx 的 `8082`
端口对主机开放。后端运行 Python 3.11，并在进程内启动线程池 Worker 和定时调度。
前端构建会执行 TypeScript 检查和 Vite 打包，再由 Nginx 提供静态文件。

`docker/rebuild.sh` 将当前 Git 提交写入后端镜像的 `BUILD_INFO`；工作区存在未提交文件时附加
`-local`。也可运行 `docker compose up -d --build`；直接构建时可用环境变量 `SOURCE_COMMIT`
指定版本标识，未指定则记为 `unknown`。

## 数据与日志

| 路径 | 用途 | 纳入 Git |
| --- | --- | --- |
| `.env` | 本机环境变量与密钥 | 否 |
| `deployment/config/searxng-settings.yml` | 本机 SearXNG 配置与密钥 | 否 |
| `mapped/data/db` | MongoDB 数据与 keyfile | 否 |
| `mapped/var/lib/redis` | Redis 持久化数据 | 否 |
| `mapped/app/data`、`mapped/app/runtime` | 应用数据、向量索引与运行文件 | 否 |
| `mapped/app/logs` | 应用文件日志目录 | 否 |
| `deployment/config/*.conf`、`logging.toml`、`*.example` | 配置及模板 | 是 |

Docker 日志采用 `json-file` 轮转：MongoDB 为 `100m × 5`，总量约 500MB；其他每个容器为
`50m × 4`，总量约 200MB。`deployment/config/logging.toml` 默认关闭应用文件日志，
由标准输出统一交给 Docker 控制容量。

Compose 设置 `SYSTEM_PROMPT_AUTO_UPDATE=false`：启动时补齐缺失的系统提示词，保留已有模板的
自定义内容。需要跟随代码自动更新已有系统模板时，可改为 `true` 并重新创建后端容器。

## 更新与运维

```bash
# 拉取代码并重新构建
git pull --ff-only
./docker/rebuild.sh

# 查看状态和日志
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 mongodb

# 重启后端
docker compose restart backend

# 停止服务
docker compose down
```

持久化数据位于宿主机 `mapped/`，停止或重新创建容器会保留这些文件。
修改 `.env` 或 Compose 环境变量后，执行 `docker compose up -d --no-build` 重新创建受影响的容器。

Python 依赖固定在 `docker/requirements.lock`，安装时校验包的 SHA256。当前 Docker 构建使用该文件，
更新 Python 依赖后应重新生成：

```bash
uv pip compile pyproject.toml --python-version 3.11 --generate-hashes \
  --output-file docker/requirements.lock
./docker/rebuild.sh
```

后端构建默认使用清华 PyPI/Debian 镜像，可通过
`docker compose build --build-arg PIP_INDEX_URL=... --build-arg APT_MIRROR=... backend` 覆盖。
本部署基于公开社区版，功能范围以仓库源码为准。
