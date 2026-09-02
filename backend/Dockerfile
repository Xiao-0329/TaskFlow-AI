# TaskFlow AI 应用镜像：FastAPI + SQLite + 静态前端，单容器
FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用镜像层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY app ./app
COPY static ./static

# 数据库与密钥落在 /app/data（挂载点）
ENV DATABASE_URL=sqlite:////app/data/taskflow.db
ENV PYTHONPYCACHEPREFIX=/tmp/.pycache

EXPOSE 8600

VOLUME ["/app/data"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
