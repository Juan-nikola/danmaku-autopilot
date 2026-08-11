# Danmaku Autopilot

面向个人 Emby 使用场景的自托管弹幕网关设计与实现项目。

> 当前状态：首个可运行版本已部署到你的 VPS。四个容器（MySQL、Misaka、`danmu_api`、Autopilot）已通过健康检查；公网 HTTPS 证书会在 Cloudflare DNS 指向 VPS 后由现有 Caddy 自动申请。

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

你的 VPS 已经由 1Panel Caddy 占用 80/443，因此不要再启动第二个 Caddy 容器。本次部署已经备份并加载了两个路由：

- `sbd-danmu.sunyz.uk`：播放器 API，反代到 `127.0.0.1:7770`，只允许播放器路径；
- `sbd-danmu-admin.sunyz.uk`：Misaka 管理页面，反代到 `127.0.0.1:7768`，额外要求 Caddy Basic Auth。

如果你在另一台机器重复部署，可在 1Panel 的 Caddy/反向代理中新增播放器域名，反向代理到：

```text
http://127.0.0.1:7770
```

由 1Panel Caddy 负责 HTTPS。不要把 `7768`、MySQL、`danmu-api` 或 Misaka 控制 API 直接暴露为端口。Misaka 管理页面也可以只通过 SSH 隧道访问：

```bash
ssh -L 7768:127.0.0.1:7768 sbdvps
```

然后在 Mac 浏览器打开 `http://127.0.0.1:7768`。

### Cloudflare 必填记录

在 `sunyz.uk` Zone 添加两条 `A` 记录，IPv4 都填 `65.75.209.243`：

```text
sbd-danmu        A        65.75.209.243
sbd-danmu-admin  A        65.75.209.243
```

先不要添加未知的 AAAA 记录。建议 Cloudflare SSL/TLS 设为 **Full (strict)**；Caddy 校验通过后会自动申请证书。DNS 生效前，HTTPS 测试出现 TLS 错误是正常的。

### Forward / SenPlayer 设置

播放器只配置网关地址，不配置 Misaka 地址：

```text
https://sbd-danmu.sunyz.uk/你的PUBLIC_API_TOKEN
```

`PUBLIC_API_TOKEN` 在 VPS 的 `.env` 中；不要把 `MISAKA_CONTROL_KEY`、`DANMU_API_TOKEN` 或 B 站 Cookie 填入播放器。也可以把 Token 放在 `Authorization: Bearer ...` 或 `X-API-Key` 请求头中。
如果播放器要求把 API 版本写在地址中，也支持 `https://sbd-danmu.sunyz.uk/你的PUBLIC_API_TOKEN/api/v2`；查询参数形式 `https://sbd-danmu.sunyz.uk/api?token=你的PUBLIC_API_TOKEN` 同样兼容。

#### Forward 首次搜索与“禁用弹幕”

首次搜索一个从未出现过的作品时，备用引擎需要并行访问多个来源，可能需要等待约 20 秒；网关会合并 Forward 同时发出的重复搜索，完成后统一返回结果。不要在几秒后连续点击搜索，也不要把“未搜索到弹幕”的旧记录当成最终结果。若旧记录已经显示为未找到，请点右侧垃圾桶删除，再输入作品名重新搜索。

播放页菜单中“禁用弹幕”旁边的勾选表示当前播放器显示开关处于关闭状态，与 API 是否找到弹幕是两件事。弹幕已匹配但仍没有显示时，点一次“禁用弹幕”取消勾选；然后重新播放或拖动进度条触发加载。当前部署已验证“一人之下 S06E14”可匹配到腾讯来源第 14 集并返回 7,761 条弹幕。

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

## 详细使用手册

### 一、第一次配置后应该怎么播放

正确保存自定义 API 后，正常播放不需要每集手动搜索：

```text
打开视频
  -> Forward 自动发送 match 请求
  -> 网关先尝试 Misaka
  -> 无匹配、空结果或超时时自动尝试 danmu_api
  -> 播放器自动请求 comment/{episodeId}
  -> 弹幕显示
```

可以直接打开一个文件名比较规范的新视频测试。只有以下情况才需要进入“搜索弹幕”：

- 首次冷搜索尚未建立缓存；
- 文件名没有季度/集数；
- 文件是合集、OVA、剧场版或补档改名；
- 自动匹配到了错误的季度；
- Forward 之前缓存过一次失败的搜索。

遇到失败记录时，先删除旧记录，再只搜索作品名称，等待约 20～30 秒。不要在冷搜索过程中反复点击搜索；多个相同请求会被网关合并，但播放器仍可能把第一次失败结果保存到本地。

### 二、Forward 的具体填写示例

在“自定义弹幕 API”中新增：

```text
名称：自用 api
地址：https://sbd-danmu.sunyz.uk/你的PUBLIC_API_TOKEN
```

不要填写以下地址：

```text
http://misaka:7768
http://danmu-api:9321
http://65.75.209.243:7768
```

这些是 Docker 内部地址或管理接口，不是播放器 API。

如果 Forward 版本要求显式填写版本路径，可以使用：

```text
https://sbd-danmu.sunyz.uk/你的PUBLIC_API_TOKEN/api/v2
```

保存后先返回视频播放页。搜索页面中的“未搜索到弹幕”是一次搜索结果，不等于服务永久没有弹幕；删除记录后重新搜索即可。

### 三、“禁用弹幕”到底是什么意思

播放页菜单中的“禁用弹幕”是播放器本地显示开关：

- 有勾：弹幕显示关闭；
- 没有勾：弹幕显示开启。

它和 API 是否找到弹幕是两件事。即使服务端已经返回大量弹幕，只要这里保持勾选，画面也不会显示。测试时建议先取消勾选，再重新播放或拖动进度条。

### 四、弹幕效果支持情况

网关会保留来源 API 返回的标准字段，但不会把不同平台的高级特效强行拼成一个格式。具体渲染由 Forward 或 SenPlayer 完成。

| 效果 | 状态 | 说明 |
| --- | --- | --- |
| 滚动/浮动 | 支持 | 保留来源的标准模式 |
| 彩色 | 支持 | 保留来源颜色值；当前测试片源有多种颜色 |
| 顶部 | 条件支持 | 来源提供且播放器支持时显示 |
| 底部 | 条件支持 | 来源提供且播放器支持时显示 |
| 时间、文本、评论 ID | 支持 | 原样保留 |
| 全局字号、透明度、显示区域、速度 | 支持 | 在播放器弹幕设置中调整 |
| 每条弹幕独立字号 | 部分支持 | 取决于来源是否提供字段 |
| B 站高级弹幕、图片、复杂动画、任意坐标 | 不保证 | 通用 API 和移动播放器通常无法完整表达 |

弹幕常见的 `p` 字段类似：

```text
1.00,1,16718180,[qq]
```

它通常包含出现时间、模式、颜色和来源标记。当前“一人之下 S06E14”的腾讯弹幕以滚动模式为主；这不代表其他 B 站、爱奇艺或弹弹 play 来源没有顶部或底部弹幕。

如果想要更接近 B 站的观感，应在 Forward/SenPlayer 的“弹幕设置”中调整显示区域、速度、字体大小、透明度和屏蔽类型。服务端不能让播放器显示播放器本身不支持的高级动画。

### 五、广告、片头和补档垫片

弹幕时间轴对应来源视频，而 Emby 文件可能已经删除广告或片头。如果视频和来源的剪辑版本不同，可能出现整体偏移：

- Emby 去掉了来源开头广告，弹幕整体提前或延后；
- 补档视频前面有很长的防删除垫片，弹幕从正片开始；
- 不同平台的片头、片尾长度不同；
- 一个文件里有多集合集，单一 episodeId 无法覆盖整个文件。

当前版本已经尽量自动选择匹配准确的来源，但不是所有广告和垫片都能自动识别。遇到时间轴不对时，先换同一作品的另一个来源，不要立即认为 Token 或 API 坏了。

## API 和架构说明

### 公网入口

```text
Forward / SenPlayer
        |
        v
Cloudflare DNS + Caddy HTTPS
        |
        v
Autopilot Gateway :7770
        |                 |
        v                 v
Misaka :7768       danmu-api :9321
        |
        v
      MySQL
```

只有 Caddy 的两个公网域名需要 DNS 记录：

```text
sbd-danmu.sunyz.uk       -> 127.0.0.1:7770
sbd-danmu-admin.sunyz.uk -> 127.0.0.1:7768
```

播放器 API 地址和 Misaka 管理后台地址必须分开。播放器不需要访问管理后台。

### 公开 API 的基本检查

健康检查不需要 Token：

```bash
curl -fsS https://sbd-danmu.sunyz.uk/healthz
```

预期结果：

```json
{"status":"ok"}
```

没有 Token 的业务请求应返回 `401`。不要为了测试把 Token 放进公开截图或 shell 历史；可以在 VPS 上直接使用播放器测试，或者在受控终端中从 `.env` 读取。

### 当前引擎策略

Misaka 是主引擎，`danmu_api` 是备用引擎。网关不会把两个引擎的 HTTP 响应简单拼在一起，因为这样会破坏播放器协议；它会先选择一个可用响应，必要时再切换备用引擎。

备用引擎仍然共用 Dallas VPS 出口。如果整台 VPS 被某个平台限流，主备引擎可能同时受影响；这时需要单独配置合规的出口或代理，而不是不停重启容器。

## VPS 运维手册

### 登录和目录

Mac 上：

```bash
ssh sbdvps
```

VPS 上：

```bash
cd /opt/danmaku-autopilot
docker compose ps
scripts/healthcheck.sh
```

项目中的 `.env`、备份、Cookie 和 Token 都属于敏感数据。不要在本地执行 `git add .` 把它们加入提交。

### 常用命令

```bash
# 只读预检
scripts/preflight.sh

# 健康检查
scripts/healthcheck.sh

# 需要时只修复被点名的应用容器
scripts/healthcheck.sh --repair

# 手动备份
scripts/backup.sh --reason manual

# 查看更新，不改变运行中的服务
scripts/update.sh --check

# 应用一个引擎的 digest 更新
scripts/update.sh --apply --engine misaka
scripts/update.sh --apply --engine danmu-api

# 回滚最近成功版本
scripts/rollback.sh latest --yes
```

更新脚本会先备份、再更新、再健康检查；不要绕过脚本直接 `docker pull ...:latest`。

### 日志排查

```bash
docker compose logs --since=10m autopilot
docker compose logs --since=10m misaka
docker compose logs --since=10m danmu-api
```

日志可能包含媒体标题、来源 URL 和错误信息。分享日志前应至少删除 Token、Cookie、Authorization、完整私有 URL 和账号信息。

### 备份和恢复

```bash
scripts/backup.sh --reason manual
ls -1 state/backups
scripts/restore.sh <backup-id> --verify
scripts/restore.sh <backup-id> --apply
```

`--verify` 不停服务；`--apply` 才会实际恢复，而且恢复前会再建立 safety backup。不要用删除 Docker 卷的方式修复普通匹配问题。

### 更新失败怎么办

先查看：

```bash
docker compose ps
scripts/healthcheck.sh
git status --short
```

更新失败时脚本会尝试恢复旧镜像锁和更新前备份。如果自动恢复仍失败，保留现场，不要删除 `state/`，把以下信息保存下来：

```bash
docker compose ps
docker compose logs --since=30m autopilot misaka danmu-api
ls -lah state/backups state/old-images.lock
```

## 安全和隐私

### 必须保密的内容

- `PUBLIC_API_TOKEN`；
- `MISAKA_CONTROL_KEY`；
- `MISAKA_PLAYER_TOKEN`；
- `DANMU_API_TOKEN`；
- MySQL 密码；
- B 站或其他平台 Cookie；
- Caddy Basic Auth 哈希和密码；
- `state/backups/` 中的所有文件。

播放器只需要 `PUBLIC_API_TOKEN`。其他密钥只给对应的服务使用，不能混填。

### 公网暴露原则

- 公网只暴露 Caddy 的 HTTPS 入口；
- 不暴露 MySQL、Misaka 控制 API 或 `danmu-api`；
- 管理后台使用独立域名和 Basic Auth；
- Cloudflare 使用 Full (strict)；
- SSH 优先使用密钥，并在确认密钥可用后关闭密码登录；
- 不在容器中挂载 Docker Socket；
- 备份文件应使用 0600 权限，最好再做加密异地备份。

## 已实现与未实现

### 已实现

- HTTPS 公网弹幕网关；
- Public Token 鉴权；
- Misaka 主引擎和 `danmu_api` 备用引擎；
- 无匹配、空评论、网络失败时自动切换；
- 冷搜索请求合并和长响应兼容处理；
- 标准弹幕时间、文本、颜色和模式透传；
- MySQL、SQLite 状态、备份、恢复、更新和回滚脚本；
- 健康检查和维护定时器；
- Forward/SenPlayer 使用的弹弹 play API 兼容入口。

### 仍受上游或播放器限制

- B 站高级弹幕、图片、复杂动画和任意坐标；
- 所有来源统一的字体、字号、渐变和特效；
- Emby 全库的提前预抓取；
- 所有广告、片头、垫片和合集的百分之百自动时间轴校正；
- 播放器手动选中的结果自动学习为永久规则；
- 被平台删除、限流、登录限制或地区限制的内容。

这些能力需要额外的来源适配、时间轴分析、持久化规则或播放器渲染能力，不是单纯修改 API 地址就能完成。

## 安全与合规

- 公网只开放播放器需要的兼容 API；数据库和内部控制接口不直接暴露。
- 不在容器中挂载 Docker Socket。
- 所有镜像按不可变 digest 锁定，更新前备份并在失败时回滚。
- 不绕过会员、付费、版权、账号或地区访问控制。
- 第三方组件遵循各自的许可证和使用条款。

## Development status

This is a personal, non-commercial, self-hosted danmaku gateway for a single user and up to three personal devices. The first implementation is intentionally fail-open: optional analysis jobs cannot prevent ordinary player responses. Live source access, image digests, Caddy DNS and cookies must be configured by the operator.
