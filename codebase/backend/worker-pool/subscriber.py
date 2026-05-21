import pika
import json
import subprocess
import time
import os
import shutil

processos_ativos = {}

def processar_video(ch, method, properties, body):
    # 1. Lê a mensagem do RabbitMQ
    mensagem = json.loads(body)
    stream_key = mensagem.get("stream_key")
    action = mensagem.get("action")

    if action == "start" and stream_key:
        print(f"[*] Iniciando transcodificação para a chave: '{stream_key}'...", flush=True)

        pasta_destino = f"/tmp/hls/{stream_key}"
        
        if os.path.exists(pasta_destino):
            print(f"[*] Limpando arquivos antigos da live '{stream_key}'...", flush=True)
            shutil.rmtree(pasta_destino)
            
        os.makedirs(pasta_destino, exist_ok=True)
        
        # 2. Monta aquele comando gigante do FFmpeg
        comando = [
            "ffmpeg",
            "-i", f"rtmp://ingest:1935/live/{stream_key}",
            "-c:v", "copy",
            "-c:a", "copy",
            "-f", "hls",
            "-hls_time", "2",
            f"{pasta_destino}/stream.m3u8"
        ]
        
        # 3. Executa o comando no terminal do contêiner
        processo = subprocess.Popen(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processos_ativos[stream_key] = processo
        
    elif action == "stop" and stream_key:
        processo = processos_ativos.get(stream_key)
        if processo:
            print(f"[*] Sinal de STOP recebido. Encerrando FFmpeg da live '{stream_key}'...", flush=True)
            
            processo.terminate()
            processo.wait()
            
            del processos_ativos[stream_key]
            print(f"[*] Live '{stream_key}' encerrada e arquivos salvos com sucesso.", flush=True)
        else:
            print(f"[!] Aviso: Recebeu STOP, mas nenhum processo rodando para '{stream_key}'.", flush=True)

    # Avisa o RabbitMQ: "Mensagem tratada, pode apagar da fila" (Serve tanto pro start quanto pro stop)
    ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    print("[*] Conectando ao RabbitMQ...", flush=True)
    
    while True:
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host='rabbitmq')
            )
            break
        except pika.exceptions.AMQPConnectionError:
            print("[!] RabbitMQ não disponível ainda. Tentando novamente em 5s...", flush=True)
            time.sleep(5)

    channel = connection.channel()

    # Garante que a fila existe
    channel.queue_declare(queue='transcode_queue', durable=True)
    
    # Diz ao RabbitMQ para enviar apenas 1 tarefa por vez para este Worker
    channel.basic_qos(prefetch_count=1)
    
    # Fica escutando a fila
    channel.basic_consume(queue='transcode_queue', on_message_callback=processar_video)

    print("[*] Worker aguardando ordens do RabbitMQ. Para sair pressione CTRL+C", flush=True)
    channel.start_consuming()

if __name__ == '__main__':
    main()