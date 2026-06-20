# 既未 · Gwei - 后端服务
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（git 用于克隆仓库）
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY pyproject.toml .

# 安装 Python 依赖
RUN pip install --no-cache-dir .

# 复制源代码
COPY src/ src/

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
