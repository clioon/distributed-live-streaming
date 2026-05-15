import redis

# conecta no Redis
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

# cria subscriber
pubsub = r.pubsub()

# se inscreve no canal
pubsub.subscribe("canal-teste")

print("Aguardando mensagens...")

# loop infinito escutando
for message in pubsub.listen():
    if message["type"] == "message":
        print(f"Mensagem recebida: {message['data']}")