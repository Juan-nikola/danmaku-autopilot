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

## 安全与合规

- 公网只开放播放器需要的兼容 API；数据库和内部控制接口不直接暴露。
- 不在容器中挂载 Docker Socket。
- 所有镜像按不可变 digest 锁定，更新前备份并在失败时回滚。
- 不绕过会员、付费、版权、账号或地区访问控制。
- 第三方组件遵循各自的许可证和使用条款。

## Development status

This is a personal, non-commercial, self-hosted danmaku gateway for a single user and up to three personal devices. The first implementation is intentionally fail-open: optional analysis jobs cannot prevent ordinary player responses. Live source access, image digests, Caddy DNS and cookies must be configured by the operator.
