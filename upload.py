#!/usr/bin/python
### edited 16.12.2024 for python 3 compat [c] Sami Karkar

import http.client as httplib
import httplib2
import os
import random
import sys
import time
import pickle # Necesario para cargar las credenciales
import argparse # Necesario para el parser de argumentos

# Importaciones específicas para las nuevas credenciales de Google Auth
import google.auth.transport.requests
import google.oauth2.credentials

from apiclient.discovery import build
from apiclient.errors import HttpError
from apiclient.http import MediaFileUpload

# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError, httplib.NotConnected,
  httplib.IncompleteRead, httplib.ImproperConnectionState,
  httplib.CannotSendRequest, httplib.CannotSendHeader,
  httplib.ResponseNotReady, httplib.BadStatusLine)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# **** EL NOMBRE DEL ARCHIVO DEL TOKEN (DEBE COINCIDIR CON autenticacion.py) ****
TOKEN_FILE_NAME = "youtube-token.pickle"

VALID_PRIVACY_STATUSES = ("public", "private", "unlisted")

# **** FUNCIÓN DE AUTENTICACIÓN MODIFICADA PARA SÓLO CARGAR EL TOKEN ****
def get_authenticated_service():
    credentials = None

    # 1. Intenta cargar las credenciales existentes
    if os.path.exists(TOKEN_FILE_NAME):
        try:
            with open(TOKEN_FILE_NAME, 'rb') as token:
                credentials = pickle.load(token)
            print(f"Credenciales de YouTube existentes en '{TOKEN_FILE_NAME}' cargadas.")
        except Exception as e:
            print(f"Error al cargar credenciales de '{TOKEN_FILE_NAME}': {e}.")
            print("Por favor, ejecuta el script de autenticación (autenticacion.py) para generar o renovar el token.")
            sys.exit(1) # Salir con un código de error

    # 2. Si no hay credenciales o no son válidas, informa y sal
    if not credentials or not credentials.valid:
        # Intenta refrescar si están expiradas y tienen un refresh_token
        if credentials and credentials.expired and credentials.refresh_token:
            print("Credenciales expiradas, intentando refrescar token...")
            try:
                credentials.refresh(google.auth.transport.requests.Request())
                with open(TOKEN_FILE_NAME, 'wb') as token: # Guarda el token refrescado
                    pickle.dump(credentials, token)
                print("Token refrescado y guardado con éxito.")
            except Exception as e:
                print(f"Error al refrescar token: {e}.")
                print("Por favor, ejecuta el script de autenticación (autenticacion.py) para generar o renovar el token.")
                sys.exit(1) # Salir con un código de error
        else: # Si no existen o no son válidas y no se pueden refrescar
            print(f"No se encontraron credenciales válidas en '{TOKEN_FILE_NAME}'.")
            print("Por favor, ejecuta el script de autenticación (autenticacion.py) para generar el token.")
            sys.exit(1) # Salir con un código de error
    
    # Construye el servicio de YouTube con las credenciales cargadas
    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)


def initialize_upload(youtube, options):
  tags = None
  if options.keywords:
    tags = options.keywords.split(",")

  body=dict(
    snippet=dict(
      title=options.title,
      description=options.description,
      tags=tags,
      categoryId=options.category
    ),
    status=dict(
      privacyStatus=options.privacyStatus
    )
  )

  insert_request = youtube.videos().insert(
    part=",".join(body.keys()),
    body=body,
    media_body=MediaFileUpload(options.file, chunksize=-1, resumable=True)
  )

  resumable_upload(insert_request)

def resumable_upload(insert_request):
  response = None
  error = None
  retry = 0
  while response is None:
    try:
      print( "Uploading file...")
      status, response = insert_request.next_chunk()
      if response is not None:
        if 'id' in response:
          print( "Video id '%s' was successfully uploaded." % response['id'])
        else:
          exit("The upload failed with an unexpected response: %s" % response)
    except HttpError as e:
      if e.resp.status in RETRIABLE_STATUS_CODES:
        error = "A retriable HTTP error %d occurred:\n%s" % (e.resp.status,
                                                             e.content)
      else:
        raise
    except Exception as e:
      if isinstance(e, RETRIABLE_EXCEPTIONS):
        error = "A retriable error occurred: %s" % e
      else:
        raise

    if error is not None:
      print( error)
      retry += 1
      if retry > MAX_RETRIES:
        exit("No longer attempting to retry.")

      max_sleep = 2 ** retry
      sleep_seconds = random.random() * max_sleep
      print( "Sleeping %f seconds and then retrying..." % sleep_seconds)
      time.sleep(sleep_seconds)

if __name__ == '__main__':
  # **** ESTE ES EL CAMBIO CLAVE: ACEPTAMOS --noauth_local_webserver AUNQUE NO LO USEMOS ****
  # Esto evita el error "unrecognized arguments" cuando lo pasas en la línea de comandos.
  parser = argparse.ArgumentParser(description="Uploads a video to YouTube.")
  parser.add_argument("--file", required=True, help="Video file to upload")
  parser.add_argument("--title", help="Video title", default="Test Title")
  parser.add_argument("--description", help="Video description",
    default="Test Description")
  parser.add_argument("--category", default="22",
    help="Numeric video category. " +
      "See https://developers.google.com/youtube/v3/docs/videoCategories/list")
  parser.add_argument("--keywords", help="Video keywords, comma separated",
    default="")
  parser.add_argument("--privacyStatus", choices=VALID_PRIVACY_STATUSES,
    default=VALID_PRIVACY_STATUSES[0], help="Video privacy status.")
  # Añadimos --noauth_local_webserver para que no dé error si se le pasa.
  # No tiene ningún efecto en este script, ya que la autenticación la hace autenticacion.py.
  parser.add_argument("--noauth_local_webserver", action="store_true", default=False,
                      help="Not used for authentication in this script, but accepted for compatibility.")

  args = parser.parse_args()

  if not os.path.exists(args.file):
    exit("Please specify a valid file using the --file= parameter.")

  # Obtiene el servicio de YouTube cargando las credenciales (NO autenticando)
  youtube = get_authenticated_service()
  try:
    initialize_upload(youtube, args)
  except HttpError as e:
    print( "An HTTP error %d occurred:\n%s" % (e.resp.status, e.content))
