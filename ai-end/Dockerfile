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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
