from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os, pickle, json

SCOPES = ['https://www.googleapis.com/auth/drive']

def main():
    creds = None
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    # Aqui vai abrir o navegador no seu PC
    creds = flow.run_local_server(port=0)

    # Salvar token.json
    with open("token.json", "w") as token:
        token.write(creds.to_json())
    print("✅ token.json gerado com sucesso!")

if __name__ == '__main__':
    main()
