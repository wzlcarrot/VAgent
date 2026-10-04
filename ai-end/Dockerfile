FROM python:3.11-slim

WORKDIR /app

# ffmpeg：faster-whisper 转写 mp4/ts 需要
# Debian 官方源在国内较慢，先切阿里云镜像再装
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 双镜像源：阿里云为主、清华兜底（官方 pypi.org 国内过慢，故不再回落）
RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    --index-url https://mirrors.aliyun.com/pypi/simple \
    --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

COPY . .

EXPOSE 8001

# --proxy-headers + --forwarded-allow-ips：采信 vagent-nginx 传来的
# X-Forwarded-For，让 auth 登录限流按真实用户 IP 计数（否则所有用户
# 共享 nginx 容器 IP，10 次失败会锁全站 15 分钟）。
# 8001 仅绑定宿主机 127.0.0.1，外部无法直连伪造头，信任 * 安全。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips", "*"]
