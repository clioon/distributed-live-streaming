FROM python:3.10-alpine

WORKDIR /app

RUN pip install Flask pika

COPY publisher.py .

CMD ["python", "publisher.py"]