# 可选服务器部署配置

教程使用本地 run.py，无需本目录。保留 Compose 和 Caddy 模板供有经验的维护者使用，未进行公网部署验收。

自行准备服务器、域名、HTTPS 反向代理登录名和密码哈希。在目标主机按 env.example 设置环境，不提交真实值。运行单个 reader 实例，数据卷必须持久保存。后台无公网端口映射，禁止直接开放 4317。

生成密码哈希可交互运行 `docker run --rm -it caddy:2-alpine caddy hash-password`，不要把明文密码写进命令参数。`docker compose config --quiet` 只检查配置，`docker compose up -d --build` 会实际启动服务。请自行验证证书、认证、来源状态和持续采集后再使用。

备份前停止 reader；禁止随意使用 `docker compose down -v`，该操作会移除数据卷。默认单人数据空间，不支持多用户隔离或多实例共用 JSON。
