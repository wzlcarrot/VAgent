FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --timeout 120 --retries 5 --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
