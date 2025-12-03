
FROM python:3.12-alpine
# FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install dependencies
RUN apk add --no-cache \
    ca-certificates \
    curl \
    python3-dev \
    git \
    ffmpeg

# Create directories
WORKDIR /app
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Set environment variables
RUN mkdir -p /app/downloads

# Copy application code
COPY ./main.py /app
COPY web /app/web

# Expose the application port
EXPOSE 5000

# Run the application
CMD ["python3", "/app/main.py"]


