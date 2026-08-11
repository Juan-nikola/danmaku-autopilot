# Danmaku Autopilot

面向个人 Emby 使用场景的自托管弹幕网关设计与实现项目。

> 当前状态：已完成可运行的首个实现骨架（Autopilot 网关、Misaka/`danmu_api` 双引擎故障转移、SQLite 任务队列、Compose/Caddy/备份更新脚本）。首次部署前仍需在你的 VPS 上完成镜像摘要解析、域名和真实接口冒烟测试。

## 项目用途

本项目计划供一名用户在 Forward、SenPlayer 等播放器中访问多个 Emby 媒体服务器时加载弹幕，预计最多同时使用三台个人设备。

播放器只需配置一个兼容弹弹play API 的 HTTPS 地址，服务端负责：

- 自动识别影片、季度和集数；
- 自动选择 Misaka、弹弹play开放弹幕网络和 `danmu_api`；
- 缓存实际播放请求产生的匹配与弹幕结果；
- 在主引擎失败或无匹配时自动切换备用引擎；
- 处理补档改名、前置广告、长时间垫片、合集拆分和时间轴偏移；
- 自动执行健康检查、备份、更新和失败回滚。

## 弹弹play开放弹幕网络

本项目计划接入[弹弹play开放弹幕网络](https://www.dandanplay.com/)，将其用于个人媒体播放时的文件识别、节目搜索和弹幕获取。

使用原则：

- 仅限个人、非商业用途；
- 仅在用户实际播放或搜索媒体时按需调用；
- 对搜索、匹配和弹幕结果进行缓存，避免重复请求；
- 不进行数据库抓取或批量下载；
- 不向第三方提供公共弹幕下载服务；
- 不将弹幕功能用于收费或商业宣传。

AppId、AppSecret、Cookie、播放器 Token 和数据库密码只保存在部署服务器的权限受限文件中，不会提交至本仓库。

## 计划架构

```text
Forward / SenPlayer
        |
        v
Caddy HTTPS
        |
        v
Autopilot Gateway
   |       |        |
   |       |        +-- 弹弹play开放弹幕网络（远程备用）
   |       +----------- danmu_api（本地备用）
   +------------------- Misaka（本地主引擎）
                            |
                           MySQL
```

## 项目文档

- [完整设计](docs/superpowers/specs/2026-08-11-automated-danmaku-service-design.md)
- [实施计划](docs/superpowers/plans/2026-08-11-automated-danmaku-service.md)
- [部署教程](docs/deployment.md)
- [部署安全说明](docs/deployment-security.md)

## 本地验证

```bash
python -m pip install -e 'autopilot[test]'
python -m pytest autopilot/tests deploy/tests -q
bash -n scripts/*.sh
```

首次部署使用 `config/env.example`、`scripts/bootstrap.sh --yes`；播放器只填写 Caddy 暴露的网关地址和 `PUBLIC_API_TOKEN`，不要填写 Misaka 控制密钥。

## 从 Mac 部署到已有 VPS

以下示例使用你的 SSH 别名 `sbdvps`。别名只保存在 Mac 的 `~/.ssh/config`，不会上传到仓库。

先确认能登录：

```bash
ssh sbdvps
```

在 VPS 上安装当前实现分支（仓库公开，不需要把密码写进命令）：

```bash
sudo mkdir -p /opt/danmaku-autopilot
sudo chown -R "$USER":"$USER" /opt/danmaku-autopilot
git clone -b codex/danmaku-implementation https://github.com/Juan-nikola/danmaku-autopilot.git /opt/danmaku-autopilot
cd /opt/danmaku-autopilot
```

首次初始化会生成随机密码、Token、权限为 `0600` 的密钥文件，并从 Docker Registry 解析 Misaka 和 `danmu_api` 的不可变 digest：

```bash
cp config/env.example .env
chmod 600 .env
nano .env                         # 至少修改域名、邮箱和 Caddy 管理密码哈希
scripts/bootstrap.sh --yes
```

你的 VPS 已经由 1Panel Caddy 占用 80/443，因此不要再启动第二个 Caddy 容器。初始化后，在 1Panel 的 Caddy/反向代理中新增一个播放器域名，例如 `danmu.example.com`，反向代理到：

```text
http://127.0.0.1:7770
```

由 1Panel Caddy 负责 HTTPS。不要把 `7768`、MySQL、`danmu-api` 或 Misaka 控制 API 代理到公网。Misaka 管理页面可以只通过 SSH 隧道访问：

```bash
ssh -L 7768:127.0.0.1:7768 sbdvps
```

然后在 Mac 浏览器打开 `http://127.0.0.1:7768`。

### Forward / SenPlayer 设置

播放器只配置网关地址，不配置 Misaka 地址：

```text
https://danmu.example.com/api?token=你的PUBLIC_API_TOKEN
```

`PUBLIC_API_TOKEN` 在 VPS 的 `.env` 中；不要把 `MISAKA_CONTROL_KEY`、`DANMU_API_TOKEN` 或 B 站 Cookie 填入播放器。也可以把 Token 放在 `Authorization: Bearer ...` 或 `X-API-Key` 请求头中。

### 日常维护

```bash
cd /opt/danmaku-autopilot
scripts/preflight.sh
scripts/healthcheck.sh
scripts/backup.sh --reason manual
scripts/update.sh --check
scripts/update.sh --apply --engine misaka
scripts/rollback.sh latest --yes
```

可选安装 `systemd/` 下的 backup、health 和 update timer；更新流程会先备份、再使用 digest 更新，健康检查失败时恢复旧版本。VPS 上已有 Watchtower 时，请确认它不会自动改写本项目容器；本项目的更新应优先使用上述事务脚本。

### 资源和安全说明

你的 VPS 只有约 3.8GiB 内存且已有其他容器。首次启动后请运行 `docker stats`；如果内存压力过高，应先降低其他容器资源或调整 Compose 限额，不要直接关闭现有服务。备份目录包含账号凭据和 Cookie，必须保持 `0600`，不要上传 GitHub 或公开网盘。

## 安全与合规

- 公网只开放播放器需要的兼容 API；数据库和内部控制接口不直接暴露。
- 不在容器中挂载 Docker Socket。
- 所有镜像按不可变 digest 锁定，更新前备份并在失败时回滚。
- 不绕过会员、付费、版权、账号或地区访问控制。
- 第三方组件遵循各自的许可证和使用条款。

## Development status

This is a personal, non-commercial, self-hosted danmaku gateway for a single user and up to three personal devices. The first implementation is intentionally fail-open: optional analysis jobs cannot prevent ordinary player responses. Live source access, image digests, Caddy DNS and cookies must be configured by the operator.
