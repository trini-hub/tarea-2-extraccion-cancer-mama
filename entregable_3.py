# -*- coding: utf-8 -*-
"""Entregable 3.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1ZTN5vfpr7wJdilTnHKMbh1Y1BduxzqfO
"""

#Instalación de librerías
!pip install transformers[torch]
!pip install accelerate
!pip install pandas spacy openpyxl
!pip install nltk==3.8.1
!python -m spacy download es_core_news_sm
!pip install tqdm

#Permisos de acceso a Google Drive para tomar las historias clínicas y poner el dataset final
from google.colab import drive
drive.mount('/content/drive/')

"""**1. Preprocesamiento de los datos**"""

import os
import pandas as pd

#Ruta a la carpeta que contiene los .txt
carpeta = "/content/drive/MyDrive/tareas_analitica_de_datos_en_salud/Tarea 2/Notas_Cancer_Mama"

#Lista para almacenar los registros
registros = []

#Recorrido por todas loas hictorias clínicas .txt
for archivo_nombre in sorted(os.listdir(carpeta)):
    if archivo_nombre.endswith(".txt"):
        id_historia = archivo_nombre.replace(".txt", "")
        ruta_archivo = os.path.join(carpeta, archivo_nombre)

        with open(ruta_archivo, "r", encoding="utf-8") as archivo:
            observacion = archivo.read().strip()
            registros.append({
                "id_historia": id_historia,
                "observacion": observacion
            })

#Creación del dataframe
df = pd.DataFrame(registros)

#Verificación del dataframe
df.head()

"""**2. Limpieza y tokenización por oración**"""

#Importar librerías
import pandas as pd
import nltk
import re
import spacy
import string
from nltk.corpus import stopwords

#Descargar tokenizador y stopwords
nltk.download('punkt')
nltk.download('stopwords')

#Cargar modelos
from nltk.tokenize import sent_tokenize
nlp = spacy.load("es_core_news_sm")
stop_words = set(stopwords.words("spanish"))

#Definir función para tokenizar oraciones
def tokenizar_por_oracion_nltk(texto):
    if pd.isna(texto):
        return []
    return sent_tokenize(texto, language="spanish")

#Tokenizar el dataframe
df["oraciones_nltk"] = df["observacion"].astype(str).apply(tokenizar_por_oracion_nltk)
df_exploded = df.explode("oraciones_nltk").dropna(subset=["oraciones_nltk"]).reset_index(drop=True) #Convierte c/d oración en una nueva fila

#Definir función para limpiar texto
def limpiar_texto(texto):
    if pd.isna(texto):
        return ""
    texto = re.sub(r'[\!\'\?\¿\¡\«\»\*\(\)\"\;]', '', texto)
    return texto.strip()

#Limpiar el dataset
df_exploded["oraciones"] = df_exploded["oraciones_nltk"].apply(limpiar_texto)
df_exploded = df_exploded[df_exploded["oraciones"].str.strip() != ""]
df_exploded = df_exploded.drop_duplicates(subset=["oraciones"]) #Eliminar oraciones duplicadas

df_exploded["oracion_id"] = range(1, len(df_exploded) + 1) #Asignar ID a c/d oración

df_final = df_exploded[["id_historia", "oracion_id", "oraciones"]]

#Verificación del dataframe
df_final.head()

"""**3. Extracción de Entidades**"""

#Importar librerías
import pandas as pd
from tqdm import tqdm
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForTokenClassification

#Cargar modelos y tokenizadores
modelo_ner = "anvorja/breast-cancer-biomedical-ner-sp-1"
modelo_nubes = "JuanSolarte99/bert-base-uncased-finetuned-ner-negation_detection_NUBES"

tokenizer_ner = AutoTokenizer.from_pretrained(modelo_ner, use_fast=True)
model_ner = AutoModelForTokenClassification.from_pretrained(modelo_ner)
tokenizer_nubes = AutoTokenizer.from_pretrained(modelo_nubes, use_fast=True)
model_nubes = AutoModelForTokenClassification.from_pretrained(modelo_nubes)

#Asignar etiquetas al modelo NUBES
id2label_nubes = {
    0: "B-NEG", 1: "B-NSCO", 2: "B-UNC", 3: "B-USCO",
    4: "I-NEG", 5: "I-NSCO", 6: "I-UNC", 7: "I-USCO", 8: "O"
}
model_nubes.config.id2label = id2label_nubes
model_nubes.eval()

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model_ner.to(device)
model_nubes.to(device)

#Definición de función para clasificar el estado lógico de las etiquetas NUBES
def clasificar_estado(entidad_start, entidad_end, zonas_negacion):
    for start_neg, end_neg, etiqueta in zonas_negacion:
        # SUPERPOSICIÓN PARCIAL
        if entidad_end > start_neg and entidad_start < end_neg:
            if etiqueta in ["B-NEG", "I-NEG", "B-NSCO", "I-NSCO"]:
                return "Negada"
            elif etiqueta in ["B-UNC", "I-UNC", "B-USCO", "I-USCO"]:
                return "Sospechosa"
    return "Afirmativa"


df = df_final

#Procesamiento por lotes
batch_size = 16
resultados = []

for start_idx in tqdm(range(0, len(df), batch_size), desc="Procesando en lotes"):
    batch = df.iloc[start_idx:start_idx + batch_size]
    textos = batch["oraciones"].tolist()
    ids = batch["id_historia"].tolist()

    #Extracción con modelo NER
    encodings_ner = tokenizer_ner(textos, return_offsets_mapping=True, padding=True,
                                  truncation=True, return_tensors="pt")
    input_ids_ner = encodings_ner["input_ids"].to(device)
    attention_mask_ner = encodings_ner["attention_mask"].to(device)
    offset_mappings = encodings_ner["offset_mapping"]

    with torch.no_grad():
        outputs_ner = model_ner(input_ids=input_ids_ner, attention_mask=attention_mask_ner)
    logits_ner = outputs_ner.logits
    predictions_ner = torch.argmax(logits_ner, dim=-1)

    #Extracción de la negación e incertidumbre
    encoding_nubes = tokenizer_nubes(textos, return_offsets_mapping=True, padding=True,
                                     truncation=True, return_tensors="pt")
    input_ids_nubes = encoding_nubes["input_ids"].to(device)
    attention_mask_nubes = encoding_nubes["attention_mask"].to(device)
    offset_mapping_nubes = encoding_nubes["offset_mapping"]

    with torch.no_grad():
        outputs_nubes = model_nubes(input_ids=input_ids_nubes, attention_mask=attention_mask_nubes)
    logits_nubes = outputs_nubes.logits
    predictions_nubes = torch.argmax(logits_nubes, dim=-1)

    for i, texto in enumerate(textos):
        ner_preds = predictions_ner[i].tolist()
        word_ids = encodings_ner.word_ids(batch_index=i)
        offsets_ner = offset_mappings[i].tolist()

        entidades = []
        temp_start, temp_end, temp_label = None, None, None

        for j, (pred_id, offset, word_id) in enumerate(zip(ner_preds, offsets_ner, word_ids)):
            if word_id is None:
                continue

            label = model_ner.config.id2label[pred_id]
            if label.startswith("B-"):
                if temp_start is not None:
                    entidad_text = texto[temp_start:temp_end]
                    entidades.append((entidad_text, temp_start, temp_end))
                temp_start, temp_end = offset
                temp_label = label[2:]
            elif label.startswith("I-") and temp_start is not None:
                temp_end = offset[1]
            else:
                if temp_start is not None:
                    entidad_text = texto[temp_start:temp_end]
                    entidades.append((entidad_text, temp_start, temp_end))
                temp_start, temp_end, temp_label = None, None, None

        if temp_start is not None:
            entidad_text = texto[temp_start:temp_end]
            entidades.append((entidad_text, temp_start, temp_end))

        zonas_negacion = []
        for j, tag_id in enumerate(predictions_nubes[i]):
            etiqueta = id2label_nubes[tag_id.item()]
            offset = offset_mapping_nubes[i][j].tolist()
            if etiqueta != "O" and offset != [0, 0]:
                zonas_negacion.append((offset[0], offset[1], etiqueta))

        #Por cada entidad NER, se evalúa si es negación o incertidumbre
        for entidad, start, end in entidades:
            estado = clasificar_estado(start, end, zonas_negacion)
            resultados.append({
                "patient_id": ids[i],
                "sentence": texto,
                "NER": entidad,
                "Estado": estado
            })


df_resultado = pd.DataFrame(resultados)
df_resultado.to_excel("/content/drive/MyDrive/tareas_analitica_de_datos_en_salud/Tarea 2/base_estructurada_final.xlsx", index=False, engine='openpyxl')