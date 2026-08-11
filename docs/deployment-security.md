# 部署安全边界

- `compose.yaml` 只发布 `127.0.0.1:7768`（Misaka 管理）和 `127.0.0.1:7770`（Autopilot）；Caddy 是唯一公网入口。
- `danmu-api` 没有 `ports`，只在 `danmu-internal` 网络提供服务。
- Compose 不挂载 `/var/run/docker.sock`；主机脚本通过 `docker compose` 管理固定项目。
- Autopilot 使用只读根文件系统，仅 `/data`、`/scratch` 和 64 MiB `/tmp` 可写；容器丢弃全部 Linux capabilities 并启用 `no-new-privileges`。
- Caddy 的播放器主机拒绝 `/api/control*`、`/docs*`、管理路径和未知上传；管理主机额外启用 Basic Auth。
- Token、Cookie、密码和控制密钥在 Git、普通访问日志和通知中不应出现。`.env`、`state/`、备份和 `deploy/images.lock` 已加入忽略规则。
- Caddy/Cloudflare 的域名必须使用 HTTPS。若 Cloudflare 使用代理，源站防火墙仍只允许 80/443 和 SSH 管理入口。
- 同一 VPS 的双引擎不是地区冗余；对 B 站、腾讯、爱奇艺等来源应在 Autopilot 配置按来源代理、限速和熔断，Cookie 仅授权访问账号已有权限的数据。
