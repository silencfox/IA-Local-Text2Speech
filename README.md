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


## Sintetizar texto
curl -s -X POST "{{base_url}}/speak" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "{{sample_text}}",
    "voice": "{{voice}}",
    "onnx_url": "{{onnx_url}}",
    "json_url": "{{json_url}}",
    "fmt": "{{fmt}}"
  }' --output salida.mp3
