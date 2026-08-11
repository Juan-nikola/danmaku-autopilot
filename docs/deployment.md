# 部署与日常维护

这套部署把 Misaka 作为主引擎、`danmu_api` 作为同机备用引擎。公网只进入 Caddy；MySQL、Misaka 控制接口和备用引擎没有公网端口。两个引擎共用 Dallas VPS 出口，所以备用引擎不能解决整台 VPS 被国内平台限流的问题。

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

现有宿主机 Caddy 使用 `config/Caddyfile.native.example`，把它复制到 Caddy 的配置目录，确认 `.env` 已被 Caddy 进程以环境变量方式读取，然后执行 `caddy validate` 和 reload：

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

播放器只填写：

```text
https://<DANMU_API_HOST>/api
```

`bootstrap.sh` 会生成最多三个独立设备 Token（`DEVICE_TOKEN_1` 到 `DEVICE_TOKEN_3`）；分别填入 Forward、SenPlayer 和第三台设备。不要把 Misaka 控制密钥或 Cloudflare Token 放入播放器。

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
