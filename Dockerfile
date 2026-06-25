FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN DJANGO_SETTINGS_MODULE=mytrack.config.settings.prod \
    DJANGO_SECRET_KEY=build-placeholder \
    DJANGO_DEBUG=False \
    POSTGRES_HOST=localhost \
    python manage.py collectstatic --noinput

EXPOSE 8001
CMD ["gunicorn", "--bind", "0.0.0.0:8001", "--worker-class", "gevent", "--workers", "3", \
     "--worker-connections", "20", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", \
     "mytrack.config.wsgi:application"]
