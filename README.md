# 抖音续火花助手（Douyin Spark Keeper）

> 本项目基于 [douyin-spark](https://github.com/Xiaowu-0916/douyin-spark) 二次开发，在原「续火花」能力之上新增了一整套**自动回复**模块。感谢原作者及下方致谢中列出的开源项目。

## ✨ 新增功能（相对原项目）

在原项目"每天定时主动发私信续火花"的基础上，本仓库新增了**被动监听 + 自动回复**能力，主要包含以下内容：

### 1. 自动回复总开关 + 独立好友名单

- 自动回复与「续火花」好友名单**完全隔离**，互不影响
- 自动回复页提供「获取聊天列表」→「勾选好友」，免手动输入，独立保存

### 2. 固定回复（支持生效时间段）

- 开启后，勾选好友发来**任意消息**，都会自动回复你指定的一句话
- 支持设置**生效时间段**（如 09:00–18:00），并支持**跨天**（如 22:00–08:00）
- 时间段之外不触发固定回复

### 3. 关键词规则（前后小框可视化配置）

- 一行一条规则：**前框**填「好友发来的关键词」，**后框**填「你要回复的内容」
- 命中关键词即回复对应文案，**优先于固定回复**
- 与固定回复可分别独立开关，互不影响

### 4. 干跑测试

- 走完整检测流程但**不真实发送**，用于验证配置是否正确
- 干跑不占用去重记录，可反复测试

### 5. 去重优化

- 按「对方消息序号」去重，好友**每发一条新消息**都会回复一次
- 即使连续发相同内容的「在吗」，也会逐条回复，避免"已读不回"

***

> 以下是原项目 [douyin-spark](https://github.com/Xiaowu-0916/douyin-spark) 的说明。

一个**自托管**的抖音"续火花"自动化工具：部署在你自己的服务器上，每天定时自动给指定好友发送一条私信，维持聊天火花（🔥）不熄灭。

提供网页管理界面，日常**完全无人值守**——只需在登录态过期时重新扫码上传一次。基于 **Python + FastAPI + Playwright** 实现，支持 Debian/Ubuntu 一键部署，可选 nginx + HTTPS 域名访问。

> ⚠️ 仅限本人账号、少量好友、每天一条的**个人自用**场景。自动化发私信违反抖音社区公约，存在被风控、限流甚至封号的风险，使用后果自负。请勿用于批量营销、多账号运营或对外提供服务。

## 功能特性

- **网页管理界面**：上传登录态、勾选续火花好友、设置发送时间、手动发送/干跑测试、查看日志，全部可视化操作
- **好友一键勾选**：从聊天列表自动读取好友（含各自火花天数），勾选即用，免手动输入
- **每日定时发送**：随机时间窗口 + 随机文案库 + 好友间随机间隔，模拟真人节奏
- **防错发保护**：点击后校验右侧会话标题，确认切对人再发送；搜索兜底直接打开会话
- **真实发送校验**：消息离开输入框才算发出，失败自动重试一次
- **当日自动补发**：本轮有失败时，约 45 分钟后自动只对失败好友补发一次（每天最多一次）
- **限流检测**：识别"操作频繁 / 安全验证"提示，命中立即停止本轮，避免误发
- **掉线提醒**：登录态失效时网页状态标红，重新扫码上传即可恢复
- **低配置可跑**：1 核 1G 内存的 Debian 服务器即可（部署脚本自动创建 2G swap）

## 工作原理

```text
你的电脑（一次性操作）                服务器（日常全自动）
┌───────────────────────────┐      ┌──────────────────────────────────┐
│ extract_cookie.py         │      │ FastAPI Web 服务（网页 UI）        │
│ 打开浏览器 → 手机扫码登录  │ 上传 │ APScheduler：每天定时触发         │
│ 导出登录态 state.json     │ ───▶ │ Playwright 无头浏览器             │
└───────────────────────────┘      │ 打开 douyin.com/chat              │
                                   │ 依次给勾选的好友发送随机文案      │
                                   │ 校验发送结果 / 失败自动补发       │
                                   │ 记录日志，掉线标红               │
                                   └──────────────────────────────────┘
```

登录态在**本机扫码获取、服务器只复用**，避免"机房 IP + 异地登录"触发风控；网页端消息同样计入火花。

## 目录结构

```text
app.py                    FastAPI 服务入口
extract_cookie.py         本机提取登录态脚本
core/automation.py        Playwright 自动化发送 / 好友列表读取
core/scheduler.py         每日定时与当日补发调度
core/config.py            配置读写
core/runtime.py           状态、日志与运行记录
static/index.html         网页管理界面（Vue 3 + Element Plus，本地资源）
deploy/deploy.sh          Debian/Ubuntu 一键部署脚本
deploy/douyin-spark.service  systemd 单元文件
data/                     运行时生成：config.json / state.json / runtime.json / logs/
```

## 快速开始

### 第一步：获取登录态（在你的 Windows/macOS 电脑上）

```bash
pip install -r requirements.txt
playwright install chromium
python extract_cookie.py
```

弹出的浏览器窗口里用手机抖音 App 扫码登录，脚本会在 `data/state.json` 导出登录态。

### 第二步：部署到服务器（Debian 13 / Ubuntu）

把整个项目目录上传到服务器（如 `/opt/douyin-spark`），然后以 root 执行：

```bash
sudo bash deploy/deploy.sh
```

脚本会自动完成：安装依赖、安装 Chromium、创建 2G swap（1G 内存服务器需要）、设置上海时区、生成随机访问令牌、注册 systemd 服务并启动。完成后会输出访问地址和令牌（保存在项目根目录 `.env`）。

> 1G 内存跑无头 Chromium 偏紧，脚本自动创建的 swap 是必需的。发送任务运行期间内存峰值约 500\~700MB。

### 第三步：网页配置

1. 打开 `http://服务器IP:8000`，输入部署时输出的访问令牌；
2. 上传第一步生成的 `data/state.json`；
3. 「好友与消息」页点「获取聊天列表」→ 勾选要续火花的好友 → 保存；
4. 「定时设置」页设置每天发送时间（默认 21:00）；
5. 先点「干跑测试」验证流程，再点「立即发送」。

之后每天自动运行。唯一的人工介入时机：网页顶部状态标红提示"登录态已过期"时，重新执行第一步并上传。

## 部署进阶：域名 + HTTPS

如果你的域名已解析到服务器（假设为 `douyin.example.com`）：

```bash
apt-get install -y nginx certbot python3-certbot-nginx

cat > /etc/nginx/sites-available/douyin-spark <<'EOF'
server {
    listen 80;
    server_name douyin.example.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/douyin-spark /etc/nginx/sites-enabled/douyin-spark
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

certbot --nginx -d douyin.example.com --non-interactive --agree-tos \
  --register-unsafely-without-email --redirect
```

并在 `.env` 中追加 `HOST=127.0.0.1`（让后端只监听本机、由 nginx 转发），然后 `systemctl restart douyin-spark`。

## 自动发送策略与保护机制

- **切换校验**：点击联系人后，必须确认右侧会话顶部标题出现目标昵称，才继续发送，杜绝"发给上一个人"。
- **搜索兜底**：列表点不到（懒加载/名字不在最近聊天）时，自动用搜索框查找并点「发消息」直接打开会话。
- **发送校验**：文字进入输入框 → 按 Enter → 文字离开输入框，三步都满足才算成功；失败自动重试一次。
- **当日补发**：本轮存在失败好友时，约 45 分钟后只对失败者补发一次；若期间一轮全部成功，补发自动取消。
- **限流熔断**：检测到"操作频繁 / 安全验证"等提示立即停止本轮，防止连续操作触发更严厉风控。
- **节奏拟人化**：发送时间有随机抖动窗口、好友之间有随机间隔、文案从模板库随机选择。

## 常见问题

- **状态显示"登录态已过期"**：本机重新运行 `extract_cookie.py`，网页重新上传即可。登录态通常能维持几天到几周。
- **好友切换失败**：优先用「获取聊天列表」勾选（取的是聊天列表真实显示名）；手动填写时用完整备注/昵称。
- **提示操作频繁**：调大"好友间隔"、减少每次发送人数；少量好友（几个到十几个）最稳。
- **服务器 IP 被风控**：优先选与日常登录城市相同的国内机房节点；海外机房 IP 更容易触发验证码。
- **网页打不开**：确认安全组/防火墙放行 8000（或 80/443）端口，且 `systemctl status douyin-spark` 正常。

## 安全与合规

- 访问令牌为随机生成，保存在 `.env`；建议再在防火墙层把管理端口限制为只有你自己的 IP 可访问。
- `state.json` 包含账号会话信息，属敏感数据，**切勿提交到仓库或分享**（`data/` 与 `.env` 已加入 `.gitignore`）。
- 本项目违反抖音社区公约中"未经平台允许采用自动化手段发私信"的规定，账号可能被限流或封禁。仅限个人低频自用，请自行承担风险。

## 致谢

发送流程与部署思路借鉴了以下开源项目（MIT 协议或公开教程）：

- [douyin-cloud-streak](https://github.com/Yuriz132/douyin-cloud-streak)
- [DouYinSparkFlow](https://github.com/2061360308/DouYinSparkFlow)
- [TikTokAutoSparkWeb](https://github.com/DkoBot/TikTokAutoSparkWeb)

## License

[MIT](./LICENSE)
