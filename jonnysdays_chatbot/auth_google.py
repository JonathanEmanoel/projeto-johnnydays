from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = ['https://www.googleapis.com/auth/calendar']
creds_path = 'client_secret.json'

def authenticate_google():
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=8080)
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())
    print("Autenticação concluída e token salvo com sucesso.")

if __name__ == '__main__':
    authenticate_google()
