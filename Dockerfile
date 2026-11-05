FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.deployment_settings
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      fonts-liberation texlive-xetex texlive-lang-cyrillic texlive-latex-extra \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 tutor && useradd -u 10001 -g tutor -M tutor \
    && install -d -o tutor -g tutor -m 0700 /var/lib/tutor

COPY requirements.txt requirements-postgres.txt ./
COPY deploy/requirements.txt deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt

COPY . .
RUN TUTOR_DATA_DIR=/tmp/tutor-build python manage.py collectstatic --noinput --ignore '*.html'

USER tutor
CMD ["sh", "-c", "umask 077 && python manage.py migrate_cabinets && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 120"]
