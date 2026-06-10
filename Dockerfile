FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

WORKDIR /code

COPY requirements.txt /code/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . /code/

ENV PORT=8000
CMD sh -c "daphne -b 0.0.0.0 -p ${PORT:-8000} LMS.asgi:application"