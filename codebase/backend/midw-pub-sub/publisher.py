import redis
import time

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

i = 0

while True:
    msg = f"Mensagem {i}"
    
    # publica no canal
    r.publish("canal-teste", msg)
    
    print(f"Enviado: {msg}")
    
    i += 1
    time.sleep(2)
