# 部署文件

- `systemd/crypto-tracker-collector.service`：加固后的采集器服务。以独立用户运行，不监听端口，凭证用 `LoadCredentialEncrypted` 加载。
- `systemd/install.sh`：安装或升级脚本。生成 release 目录并切换 `current` 软链接，同时创建用户、目录和权限。
- `requirements.lock.txt`：由 `uv export --frozen --no-dev --no-emit-project` 生成的带哈希依赖清单，供没有 uv 的主机用 `pip --require-hashes` 安装。

完整步骤见 [../docs/HERMES-SETUP.zh-CN.md](../docs/HERMES-SETUP.zh-CN.md)。原项目的 Docker Compose 和 Caddy 公网部署已移除（审计 S4）。
