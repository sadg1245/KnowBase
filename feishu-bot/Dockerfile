FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (none needed - all pure Python packages)

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn

# Copy application code
COPY . .

# Run the bot
CMD ["python", "-m", "bot.main"]
