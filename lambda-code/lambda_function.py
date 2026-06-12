import boto3
import csv
import json
import io
import uuid
import time
import os
from datetime import datetime
from urllib.parse import unquote_plus

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
dynamodb = boto3.resource("dynamodb")

CURATED_BUCKET = "tickets-curated-grupo5"
DYNAMO_TABLE = "ticket_execution_log"

MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
TAMANO_LOTE = 5

tabla_log = dynamodb.Table(DYNAMO_TABLE)


def dividir_en_lotes(lista, tamano):
    for i in range(0, len(lista), tamano):
        yield lista[i:i + tamano]


def existe_en_s3(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def obtener_curated_key(raw_key):
    nombre_archivo = os.path.basename(raw_key)
    nombre_sin_extension = os.path.splitext(nombre_archivo)[0]

    partes = raw_key.split("/")

    if len(partes) >= 4:
        anio = partes[1]
        mes = partes[2]
        return f"curated/{anio}/{mes}/{nombre_sin_extension}_clasificado.csv"

    return f"curated/{nombre_sin_extension}_clasificado.csv"


def extraer_json(texto):
    texto = texto.strip()
    texto = texto.replace("```json", "").replace("```", "").strip()

    inicio = texto.find("[")
    fin = texto.rfind("]")

    if inicio != -1 and fin != -1:
        texto = texto[inicio:fin + 1]

    return json.loads(texto)


def clasificar_lote(tickets):
    tickets_prompt = [
        {
            "ticket_id": t["ticket_id"],
            "mensaje_usuario": t["mensaje_usuario"]
        }
        for t in tickets
    ]

    prompt = f"""
Clasifica la prioridad de los siguientes tickets de soporte.

Responde únicamente un arreglo JSON válido.
No agregues explicación, no uses markdown, no uses ```.

Prioridades permitidas:
Alta, Media, Baja.

Criterios:
- Alta: si el usuario no puede acceder, tiene problemas de credenciales, bloqueo total, caída del sistema o problema crítico.
- Media: si hay error técnico, contenido que no se visualiza, configuración incorrecta o afecta parcialmente el uso.
- Baja: si es una consulta, solicitud informativa, demo, coaching, reposición, creación o requerimiento no urgente.

Formato exacto:
[
  {{"ticket_id": "TICKET-001", "prioridad": "Alta"}},
  {{"ticket_id": "TICKET-002", "prioridad": "Baja"}}
]

Tickets:
{json.dumps(tickets_prompt, ensure_ascii=False)}
"""

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
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
    texto = response_body["content"][0]["text"].strip()

    print("Respuesta Bedrock:")
    print(texto)

    try:
        resultado_json = extraer_json(texto)
    except Exception as e:
        print(f"Error leyendo JSON de Bedrock: {str(e)}")
        resultado_json = []

    prioridades = {}

    for item in resultado_json:
        ticket_id = str(item.get("ticket_id", "")).strip()
        prioridad = str(item.get("prioridad", "Media")).strip().lower()

        if prioridad == "alta":
            prioridades[ticket_id] = "Alta"
        elif prioridad == "baja":
            prioridades[ticket_id] = "Baja"
        else:
            prioridades[ticket_id] = "Media"

    return prioridades


def lambda_handler(event, context):
    tiempo_inicio = time.time()
    execution_id = str(uuid.uuid4())
    fecha_inicio = datetime.utcnow().isoformat()

    try:
        raw_bucket = event["Records"][0]["s3"]["bucket"]["name"]
        raw_key = unquote_plus(event["Records"][0]["s3"]["object"]["key"])

        nombre_archivo = os.path.basename(raw_key)
        curated_key = obtener_curated_key(raw_key)

        archivo_origen = f"s3://{raw_bucket}/{raw_key}"
        archivo_salida = f"s3://{CURATED_BUCKET}/{curated_key}"

        print(f"Procesando archivo: {archivo_origen}")
        print(f"Archivo de salida: {archivo_salida}")

        if not raw_key.lower().endswith(".csv"):
            print("No es CSV. Se omite.")
            return {"statusCode": 200, "body": "Archivo omitido. No es CSV."}

        if existe_en_s3(CURATED_BUCKET, curated_key):
            print("Archivo ya procesado. Se omite.")

            tabla_log.put_item(
                Item={
                    "execution_id": execution_id,
                    "archivo_origen": archivo_origen,
                    "archivo_salida": archivo_salida,
                    "estado": "OMITIDO",
                    "motivo": "Archivo ya procesado",
                    "fecha_inicio": fecha_inicio,
                    "fecha_fin": datetime.utcnow().isoformat(),
                    "modelo_usado": MODEL_ID,
                    "nombre_archivo": nombre_archivo
                }
            )

            return {
                "statusCode": 200,
                "body": json.dumps({
                    "mensaje": "Archivo ya procesado. Se omitió.",
                    "archivo_origen": archivo_origen,
                    "archivo_salida": archivo_salida
                })
            }

        tabla_log.put_item(
            Item={
                "execution_id": execution_id,
                "archivo_origen": archivo_origen,
                "estado": "EN_PROCESO",
                "fecha_inicio": fecha_inicio,
                "modelo_usado": MODEL_ID,
                "tamano_lote": TAMANO_LOTE,
                "nombre_archivo": nombre_archivo
            }
        )

        objeto = s3.get_object(Bucket=raw_bucket, Key=raw_key)
        raw_data = objeto["Body"].read()

        try:
            contenido = raw_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            contenido = raw_data.decode("latin-1")

        lector = csv.DictReader(io.StringIO(contenido), delimiter=";")

        tickets = []

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

            tickets.append({
                "ticket_id": fila_limpia.get("ticket_id", ""),
                "fecha_creada": fila_limpia.get("fecha_creada", ""),
                "canal": fila_limpia.get("canal", ""),
                "mensaje_usuario": mensaje,
                "archivo_origen": nombre_archivo
            })

        resultados = []
        total_lotes = 0

        for lote in dividir_en_lotes(tickets, TAMANO_LOTE):
            total_lotes += 1
            print(f"Procesando lote {total_lotes} con {len(lote)} tickets")

            prioridades_lote = clasificar_lote(lote)

            for ticket in lote:
                ticket_id = ticket["ticket_id"]
                prioridad = prioridades_lote.get(ticket_id, "Media")

                resultados.append({
                    "ticket_id": ticket_id,
                    "fecha_creada": ticket["fecha_creada"],
                    "canal": ticket["canal"],
                    "mensaje_usuario": ticket["mensaje_usuario"],
                    "prioridad": prioridad,
                    "archivo_origen": ticket["archivo_origen"]
                })

        output = io.StringIO()

        campos = [
            "ticket_id",
            "fecha_creada",
            "canal",
            "mensaje_usuario",
            "prioridad",
            "archivo_origen"
        ]

        writer = csv.DictWriter(output, fieldnames=campos)
        writer.writeheader()
        writer.writerows(resultados)

        s3.put_object(
            Bucket=CURATED_BUCKET,
            Key=curated_key,
            Body=output.getvalue().encode("utf-8-sig"),
            ContentType="text/csv"
        )

        duracion_segundos = round(time.time() - tiempo_inicio, 2)

        tabla_log.update_item(
            Key={"execution_id": execution_id},
            UpdateExpression="""
                SET estado = :estado,
                    fecha_fin = :fecha_fin,
                    cantidad_tickets = :cantidad_tickets,
                    archivo_salida = :archivo_salida,
                    total_lotes = :total_lotes,
                    duracion_segundos = :duracion_segundos
            """,
            ExpressionAttributeValues={
                ":estado": "COMPLETADO",
                ":fecha_fin": datetime.utcnow().isoformat(),
                ":cantidad_tickets": len(resultados),
                ":archivo_salida": archivo_salida,
                ":total_lotes": total_lotes,
                ":duracion_segundos": str(duracion_segundos)
            }
        )

        print("Proceso completado correctamente")
        print(f"Archivo procesado: {nombre_archivo}")
        print(f"Tickets procesados: {len(resultados)}")
        print(f"Total lotes: {total_lotes}")
        print(f"Duración: {duracion_segundos} segundos")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "mensaje": "Archivo procesado automáticamente por S3",
                "execution_id": execution_id,
                "archivo_procesado": nombre_archivo,
                "cantidad_tickets": len(resultados),
                "tamano_lote": TAMANO_LOTE,
                "total_lotes": total_lotes,
                "duracion_segundos": duracion_segundos,
                "archivo_salida": archivo_salida
            })
        }

    except Exception as e:
        duracion_segundos = round(time.time() - tiempo_inicio, 2)

        tabla_log.put_item(
            Item={
                "execution_id": execution_id,
                "estado": "ERROR",
                "fecha_inicio": fecha_inicio,
                "fecha_fin": datetime.utcnow().isoformat(),
                "mensaje_error": str(e),
                "duracion_segundos": str(duracion_segundos),
                "modelo_usado": MODEL_ID
            }
        )

        print(f"ERROR: {str(e)}")
        raise e
