FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# 双镜像源：清华为主、官方 PyPI 兜底，避免单一源故障导致 build 失败
RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    --extra-index-url https://pypi.org/simple \
    -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
