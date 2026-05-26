import pika
import json
from flask import Flask, request

app = Flask(__name__)

def enviar_para_fila(action, stream_key):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq'))
        channel = connection.channel()
        channel.queue_declare(queue='transcode_queue', durable=True)
        
        mensagem = {"action": action, "stream_key": stream_key}
        
        channel.basic_publish(
            exchange='',
            routing_key='transcode_queue',
            body=json.dumps(mensagem)
        )
        connection.close()
    except Exception as e:
        print(f"Erro no RabbitMQ: {e}", flush=True)

@app.route('/on_publish', methods=['POST'])
def on_publish():
    stream_key = request.form.get('name')
    print(f"[+] NOVA LIVE: '{stream_key}'. Enviando START para a fila.", flush=True)
    enviar_para_fila("start", stream_key)
    return "OK", 200

@app.route('/on_publish_done', methods=['POST'])
def on_publish_done():
    stream_key = request.form.get('name')
    print(f"[-] FIM DA LIVE: '{stream_key}'. Enviando STOP para a fila.", flush=True)
    enviar_para_fila("stop", stream_key)
    return "OK", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)