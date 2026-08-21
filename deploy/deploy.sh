#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "请以 root 运行：sudo bash deploy/deploy.sh"
  exit 1
fi

SERVICE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$SERVICE_DIR/.venv"
UNIT_SRC="$SERVICE_DIR/deploy/douyin-spark.service"
UNIT_DST="/etc/systemd/system/douyin-spark.service"

echo "==> 安装系统依赖"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip

echo "==> 创建 Python 虚拟环境"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

echo "==> 安装 Python 依赖"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$SERVICE_DIR/requirements.txt"

echo "==> 安装 Chromium（首次需下载数百 MB）"
"$VENV/bin/playwright" install --with-deps chromium

echo "==> 配置 2G 交换空间（1G 内存服务器跑浏览器需要）"
if ! swapon --show | grep -q 'swap'; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "swap 已创建并启用"
else
  echo "检测到已有 swap，跳过"
fi

echo "==> 设置时区为 Asia/Shanghai"
timedatectl set-timezone Asia/Shanghai || echo "无法设置时区（容器环境可忽略）"

echo "==> 生成访问令牌"
if [ ! -f "$SERVICE_DIR/.env" ]; then
  TOKEN="$(head -c 24 /dev/urandom | sha256sum | head -c 32)"
  cat > "$SERVICE_DIR/.env" <<EOF
AUTH_TOKEN=$TOKEN
PORT=8000
EOF
fi
TOKEN_VALUE="$(grep '^AUTH_TOKEN=' "$SERVICE_DIR/.env" | cut -d= -f2- | tr -d '\r\n')"
if [ -z "$TOKEN_VALUE" ]; then
  TOKEN_VALUE="$(head -c 24 /dev/urandom | sha256sum | head -c 32)"
  sed -i "s/^AUTH_TOKEN=.*/AUTH_TOKEN=$TOKEN_VALUE/" "$SERVICE_DIR/.env"
fi

echo "==> 安装 systemd 服务"
sed "s|__DIR__|$SERVICE_DIR|g; s|__VENV__|$VENV|g" "$UNIT_SRC" > "$UNIT_DST"
systemctl daemon-reload
systemctl enable --now douyin-spark
sleep 2
systemctl --no-pager --lines=5 status douyin-spark || true

IP="$(hostname -I | awk '{print $1}')"
echo ""
echo "======================================================"
echo "部署完成！"
echo "网页地址: http://$IP:8000"
echo "访问令牌: $TOKEN_VALUE"
echo "令牌保存在: $SERVICE_DIR/.env"
echo "======================================================"
echo "接下来："
echo "1. 在你的 Windows 电脑上运行 python extract_cookie.py 生成 data/state.json"
echo "2. 打开网页 -> 输入令牌 -> 上传登录态 -> 配置好友与发送时间"
echo "3. 点「干跑测试」验证流程无误后，再点「立即发送」"
