# KDvops TTS (Piper)

## Levantar
docker compose up -d --build

## Listar voces
curl -s http://localhost:8080/voices | jq

## Sintetizar texto
curl -s -X POST http://localhost:8080/speak \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Hola, soy KDvops. Orquestando nubes con automatización.",
    "voice": "es_ES"
  }' \
  --output salida.mp3
