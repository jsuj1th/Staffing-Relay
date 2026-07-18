FROM python:3.12-slim

WORKDIR /app

# Which settings to build/run with. Default = single-box (WhiteNoise static, no
# S3). Override for the ECS path: --build-arg DJANGO_SETTINGS_MODULE=lms.settings.production
ARG DJANGO_SETTINGS_MODULE=lms.settings.singlebox
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE} \
    DEBUG=False

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "lms.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60"]
