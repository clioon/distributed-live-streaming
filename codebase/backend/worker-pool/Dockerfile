FROM python:3.10-alpine

# Instala o FFmpeg no Linux
RUN apk add --no-cache ffmpeg bash

WORKDIR /app

# Instala a biblioteca do RabbitMQ
RUN pip install pika

# Copia o nosso script
COPY subscriber.py .

# Cria a pasta onde os vídeos serão salvos
RUN mkdir -p /tmp/hls

# Roda o nosso script Python (o -u força os prints a aparecerem na hora no terminal)
CMD ["python", "-u", "subscriber.py"]