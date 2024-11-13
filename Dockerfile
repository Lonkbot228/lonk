FROM python:3.10

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN apt-get update && \
    apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libxdamage1 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-xcb1 \
    fonts-liberation \
    libappindicator3-1 \
    libxshmfence1 \
    libgtk-3-0 && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

COPY . /app

CMD ["python", "main.py"]
