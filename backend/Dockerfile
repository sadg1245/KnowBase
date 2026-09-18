FROM public.ecr.aws/docker/library/python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface

COPY requirements.txt .

# Install the CPU-only PyTorch wheel before sentence-transformers to avoid
# pulling CUDA runtime packages into the API and worker image.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir jieba==0.42.1

FROM base AS dev

COPY . .
# /app/data 是持久化卷挂载点：数据库、受控媒体、密钥、备份与嵌入向量库都在其中。
RUN mkdir -p /app/data/sqlite /app/data/uploads /app/data/media \
    /app/data/secrets /app/data/backups /app/uploads

EXPOSE 8000

# Upgrade the schema before the API starts; a failed migration stops startup
# so the API never serves requests against an out-of-date structure.
CMD ["sh", "-c", "python -m app.cli migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]


FROM base AS production

COPY . .
RUN mkdir -p /app/data/sqlite /app/data/uploads /app/data/media \
    /app/data/secrets /app/data/backups /app/uploads

EXPOSE 8000

CMD ["sh", "-c", "python -m app.cli migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
