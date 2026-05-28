import boto3
import csv
import json
import io
from datetime import datetime

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

RAW_BUCKET = "tickets-raw-grupo5"
RAW_KEY = "raw/TICKETS.csv"

CURATED_BUCKET = "tickets-curated-grupo5"
CURATED_KEY = "curated/tickets_clasificados.csv"

MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def clasificar_ticket(mensaje):
    prompt = f"""
Clasifica la prioridad del siguiente ticket de soporte.

Debes responder SOLO una palabra:
Alta, Media o Baja.

Criterios:
- Alta: si el usuario no puede acceder, no puede usar la plataforma, hay caída del sistema, bloqueo total o problema crítico.
- Media: si hay error técnico, contenido que no se visualiza, problemas de configuración o afecta parcialmente el uso.
- Baja: si es una consulta, solicitud informativa, creación de recurso, demo, coaching o requerimiento no urgente.

Ticket:
"{mensaje}"
"""

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 20,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    }

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json"
    )

    response_body = json.loads(response["body"].read())
    prioridad = response_body["content"][0]["text"].strip()

    if "alta" in prioridad.lower():
        return "Alta"
    elif "baja" in prioridad.lower():
        return "Baja"
    elif "media" in prioridad.lower():
        return "Media"
    else:
        return "Media"


def lambda_handler(event, context):
    # 1. Leer CSV desde S3 Raw
    objeto = s3.get_object(Bucket=RAW_BUCKET, Key=RAW_KEY)

    raw_data = objeto["Body"].read()

    try:
        contenido = raw_data.decode("utf-8-sig")
    except UnicodeDecodeError:
        contenido = raw_data.decode("latin-1")

    lector = csv.DictReader(io.StringIO(contenido), delimiter=";")
    resultados = []

    # 2. Procesar cada ticket
    for fila in lector:
        fila_limpia = {
            str(k).strip().lower(): v
            for k, v in fila.items()
            if k is not None
        }

        mensaje = (
            fila_limpia.get("mensaje_usuario")
            or fila_limpia.get("mesage_usuario")
            or fila_limpia.get("message_usuario")
            or fila_limpia.get("customer_message")
        )

        if not mensaje:
            continue

        prioridad = clasificar_ticket(mensaje)

        resultados.append({
            "ticket_id": fila_limpia.get("ticket_id", ""),
            "fecha_creada": fila_limpia.get("fecha_creada", ""),
            "canal": fila_limpia.get("canal", ""),
            "mensaje_usuario": mensaje,
            "prioridad": prioridad
        })

    # 3. Crear CSV de salida
    output = io.StringIO()
    campos = [
    "ticket_id",
    "fecha_creada",
    "canal",
    "mensaje_usuario",
    "prioridad"
    ]

    writer = csv.DictWriter(output, fieldnames=campos)
    writer.writeheader()
    writer.writerows(resultados)

    # 4. Guardar resultado en S3 Curated
    s3.put_object(
        Bucket=CURATED_BUCKET,
        Key=CURATED_KEY,
        Body=output.getvalue().encode("utf-8-sig"),
        ContentType="text/csv"
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "mensaje": "Tickets clasificados correctamente",
            "cantidad_tickets": len(resultados),
            "archivo_salida": f"s3://{CURATED_BUCKET}/{CURATED_KEY}"
        })
    }
