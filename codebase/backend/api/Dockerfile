FROM python:3.10-alpine

WORKDIR /app

RUN pip install Flask pika

COPY app.py .

CMD ["python", "app.py"]