# 部署与日常维护

这套部署把 Misaka 作为主引擎、`danmu_api` 作为同机备用引擎。公网只进入 Caddy；MySQL、Misaka 控制接口和备用引擎没有公网端口。两个引擎共用 Dallas VPS 出口，所以备用引擎不能解决整台 VPS 被国内平台限流的问题。

Misaka 和 `danmu_api` 都连接 `danmu-egress`，并固定使用 `1.1.1.1`、`8.8.8.8` 解析源站域名。这样可以避免某些 VPS 的 Docker 内置 DNS 对 B 站/爱奇艺接口返回 `EAI_AGAIN`；如果 DNS 正常但仍然无匹配，通常是源站超时、地区限制、登录 Cookie 或出口 IP 限流，需要查看对应容器日志，不能靠反复重启解决。

## 首次初始化

在已经安装 Docker Compose v2、Caddy 和 Git 的 VPS 上：

```bash
cp config/env.example .env
chmod 600 .env
# 编辑域名、邮箱；密码和 Token 可留给 bootstrap 自动生成
scripts/bootstrap.sh --yes
```

`bootstrap.sh` 会创建 `state/secrets/`（每个文件 `0600`）、校验 Compose、创建持久化卷并启动服务。重复执行不会轮换已有密码；需要轮换时显式指定，例如：

```bash
scripts/bootstrap.sh --rotate PUBLIC_API_TOKEN --yes
```

镜像必须写在 `deploy/images.lock` 并含 `sha256:` 不可变摘要。`deploy/images.lock.example` 只是格式示例，不能直接用于生产；由镜像解析步骤替换其中的占位摘要。

## Caddy 与 Cloudflare

现有宿主机 Caddy 使用 `config/Caddyfile.native.example`。如果沿用本项目的现成 VPS，部署脚本之外的 Caddy 路由已经写入 1Panel Caddy 配置并完成 `validate`/reload；配置备份位于同目录的 `Caddyfile.bak.<时间戳>`。如果是另一台机器，把模板复制到 Caddy 配置目录，确认 `.env` 已被 Caddy 进程以环境变量方式读取，然后执行 `caddy validate` 和 reload：

```bash
cp state/caddy/Caddyfile /etc/caddy/danmu.Caddyfile
caddy validate --config /etc/caddy/danmu.Caddyfile
systemctl reload caddy
```

Cloudflare 仅需要对应 Zone 的 DNS Edit/Read 权限。先预览两条记录，再明确 `--apply`：

```bash
scripts/cloudflare-dns.sh
scripts/cloudflare-dns.sh --apply
```

脚本只处理 `DANMU_API_HOST` 和 `DANMU_ADMIN_HOST` 两个精确主机名，不会改动同一区域的其他记录。

本次 VPS 使用以下记录，IPv4 都是 `65.75.209.243`：

```text
sbd-danmu        A        65.75.209.243
sbd-danmu-admin  A        65.75.209.243
```

没有已确认的 IPv6 时不要添加 AAAA。Cloudflare 建议使用 **Full (strict)**；DNS 生效后 Caddy 才能为两个域名完成公网证书申请。

当前网关播放器鉴权使用同一个 `PUBLIC_API_TOKEN`；三台个人设备可以使用同一个 URL。`DEVICE_TOKEN_1` 到 `DEVICE_TOKEN_3` 是后续细分设备权限的预留字段，当前不要拿它们替换公共 Token。播放器只填写：

```text
https://<DANMU_API_HOST>/api
```

`PUBLIC_API_TOKEN` 在 VPS 的 `.env` 中；不要把 Misaka 控制密钥、备用引擎 Token、Cookie 或 Cloudflare Token 放入播放器。

如果 Dallas 出口仍无法访问某些国内源，Snell“节点服务端”本身不会自动让 Docker 使用代理；必须在 VPS 上另行运行 Snell 客户端，并提供本地 HTTP/SOCKS 监听端口，再把该端口接入来源请求。没有本地监听端口时，不要把 Snell 的服务端端口直接填到这里。

设置 Caddy Basic Auth 时，请把 `caddy hash-password` 输出的 `$2a$...` 整段用单引号包住；脚本会读取 `.env`，未加引号的 `$` 会被 shell 展开。

## 健康检查与故障排查

```bash
scripts/preflight.sh
scripts/healthcheck.sh
scripts/healthcheck.sh --repair   # 只重启被点名的应用容器
```

`preflight.sh` 是只读检查：Docker、Compose、DNS、磁盘和本机绑定端口。健康检查失败时先看 `docker compose ps` 和对应服务日志，不要删除卷。只有完全确认数据不需要时才执行卷清理，并应先做备份。

## 备份与恢复

备份会锁定维护操作，导出 MySQL、Autopilot SQLite、两个引擎的配置/缓存、`.env`、密钥和镜像锁，最后才写入带 SHA-256 清单的目录：

```bash
scripts/backup.sh --reason daily
scripts/backup.sh --reason pre-update
scripts/restore.sh <backup-id> --verify
```

`--verify` 永远不会停服务。真正恢复必须显式使用 `--apply`；恢复前脚本会再建立一份 safety backup：

```bash
scripts/restore.sh <backup-id> --apply
```

备份目录含账号 Cookie 和 Token，必须使用磁盘权限、加密卷或 restic 做额外保护，绝不能提交 Git。异地备份配置好 `RESTIC_REPOSITORY` 后，由管理员在受控环境执行上传和恢复演练。

## 更新与回滚

先查看差异：

```bash
scripts/update.sh --check
```

应用更新时一次只操作一个引擎，流程顺序固定为“锁维护 → pre-update 备份 → 拉取镜像 → 重建 → 健康检查”。失败时自动恢复旧锁和备份；也可以手动指定备用引擎：

```bash
scripts/update.sh --apply --engine misaka
scripts/update.sh --apply --engine danmu-api
```

回滚需要成功版本或备份 ID。`latest` 取最近一次成功版本，而不是随便取最新目录；默认要求确认，自动化调用才使用 `--yes`：

```bash
scripts/rollback.sh latest
scripts/rollback.sh <backup-id> --yes
```

MySQL 固定为 `mysql:8.1.0-oracle`，不会随应用更新自动升级。

## 自动维护（可选）

仓库提供 systemd 模板。把 `/opt/danmaku-autopilot` 改成实际目录后安装并启用：

```bash
sudo cp systemd/danmu-{backup,health,update}.service systemd/danmu-{backup,health,update}.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now danmu-backup.timer danmu-health.timer danmu-update.timer
```

更新定时器先解析新的不可变摘要，再执行“备份 → 更新 → 健康检查 → 失败恢复”；首次启用前建议先手动运行 `scripts/update.sh --check`。
