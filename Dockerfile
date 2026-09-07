FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install LibreOffice headless and fonts for authentic Word document preview
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer-nogui \
    default-jre-headless \
    fonts-dejavu \
    fonts-liberation \
    fontconfig \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads/generated_documents uploads/documents uploads/resumes uploads/preview_cache

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "app:app"]
