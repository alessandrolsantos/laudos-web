from flask import send_file
import os, re, tempfile
from flask import Flask, request, render_template_string
from datetime import datetime, timedelta
# Google Drive API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
from flask import redirect
import io
import unicodedata

STORAGE_PROVIDER = os.environ.get("STORAGE_PROVIDER", "google_drive")

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>Epicentro Curitiba - Consulta de Laudo</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root { font-family: system-ui, Arial, sans-serif; }
    body { background:#f6f7fb; padding: 24px; }
    .card { max-width:420px; margin:40px auto; background:#fff; padding:24px; border-radius:14px; box-shadow:0 10px 30px rgba(0,0,0,.06); }
    .logo { text-align:center; margin-bottom:12px; }
    .logo img { max-width:160px; height:auto; }
    h1 { margin:8px 0 10px; font-size:22px; font-weight:600; color:#1B399E; }
    p.muted{color:#555; margin-top:0; font-size:15px; line-height:1.4;}
    label{display:block; font-size:15px; margin:14px 0 6px; font-weight:500; color:#333;}
    input{width:100%; box-sizing:border-box; padding:14px; border:1px solid #d7d9e0; border-radius:10px; font-size:17px; margin:0 0 6px 0; transition:border .15s;}
    input:focus { border:2px solid #1B399E; outline:none; }
    button{
      width:100%; padding:16px; margin-top:16px; margin-bottom:8px; border:0; border-radius:10px; font-size:18px; cursor:pointer;
      background: #1B399E; color:#fff; font-weight:600; box-shadow:0 2px 8px rgba(27,57,158,0.12);
      transition: background 0.2s;
    }
    button:active { background:#14295d; }
    .error{display:flex; align-items:center; color:#c02626; background:#fdecec; padding:10px 12px; border-radius:10px; font-size:15px; margin-bottom:12px; margin-top:7px;}
    .error::before { content:"✗"; display:inline-block; margin-right:8px; font-size:20px; }
    .success{background:#ecfdf5; color:#065f46; padding:14px 14px; border-radius:12px; margin-top:16px; font-size:15px; border:1px solid #34d399;}
    .success strong { display:block; font-size:16px; margin-bottom:6px; }
    a.btn{display:inline-block; margin-top:12px; text-decoration:none; background:#10b981; color:#fff; padding:12px 16px; border-radius:10px; font-weight:500; font-size:16px;}
    a.btn:hover{background:#059669;}
    small{display:block; margin-top:12px; color:#777; font-size:13px;}
    #aguarde-overlay {
      display:none; position:fixed; z-index:9999; top:0; left:0; width:100vw; height:100vh;
      background:rgba(255,255,255,0.85); align-items:center; justify-content:center;
    }
    .spinner {
      border: 6px solid #e5e7eb;
      border-top: 6px solid #2563eb;
      border-radius: 50%;
      width: 48px;
      height: 48px;
      animation: spin 1s linear infinite;
      margin:auto;
    }
    @keyframes spin {
      0% { transform: rotate(0deg);}
      100% { transform: rotate(360deg);}
    }
    #aguarde-msg { text-align:center; color:#2563eb; font-size:18px; margin-top:18px;}
    @media (max-width:500px){
      .card{max-width:98vw; padding:10vw 2vw;}
      h1{font-size:18px;}
      .logo img{max-width:80px;}
      button{font-size:16px; padding:14px;}
      input{font-size:15px; padding:12px;}
    }
  </style>
</head>
<body>
  <div id="aguarde-overlay">
    <div>
      <div class="spinner"></div>
      <div id="aguarde-msg">Preparando download...</div>
    </div>
  </div>
  <div class="card">
    <div class="logo">
      <img src="{{ url_for('static', filename='logo_epicentro.png') }}" alt="Epicentro - Centro de Diagnóstico e Tratamento de Epilepsia">
    </div>
    <h1>Consulta de Laudo</h1>
    <p class="muted">Informe o <b>primeiro nome do paciente</b> e o <b>código do exame</b> para visualizar o laudo.</p>
    <form method="post" novalidate id="laudo-form" autocomplete="off">
      <label for="primeiro_nome">Primeiro nome do paciente</label>
      <input id="primeiro_nome" name="primeiro_nome" type="text" required autofocus placeholder="Exemplo: Maria" aria-label="Primeiro nome">
      <label for="codigo">Código do exame</label>
      <input id="codigo" name="codigo" type="text" required placeholder="Ex.: 123456" inputmode="numeric" aria-label="Código do exame">
      <button type="submit">Consultar laudo</button>
      {% if erro %}
        <div class="error">{{ erro }}</div>
      {% endif %}
    </form>
    {% if link %}
      <div class="success">
        <strong>✅ Seu laudo está disponível!</strong>
        <div><a class="btn" href="{{ link }}">📄 Baixar laudo</a></div>
        <small>Guarde este link em local seguro. Compartilhe apenas com profissionais autorizados.</small>
      </div>
    {% endif %}
  </div>
  <script>
    document.getElementById('laudo-form').addEventListener('submit', function(e) {
      const codigo = document.getElementById('codigo').value.trim();
      const primeiro_nome = document.getElementById('primeiro_nome').value.trim();
      if (!codigo || codigo.length < 3) {
        e.preventDefault();
        alert("Por favor, insira um código de exame válido.");
        return;
      }
      if (!primeiro_nome || primeiro_nome.length < 2) {
        e.preventDefault();
        alert("Por favor, insira o primeiro nome do paciente.");
        return;
      }
      document.getElementById('aguarde-overlay').style.display = 'flex';
    });
  </script>
</body>
</html>

"""

PORTUGUESE_MONTHS = {
    "jan": "01", "fev": "02", "mar": "03", "abr": "04",
    "mai": "05", "jun": "06", "jul": "07", "ago": "08",
    "set": "09", "out": "10", "nov": "11", "dez": "12"
}



def remover_acentos(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )


@app.route("/")
def home():
    return redirect("/laudos")

def get_token_path():
    token_env = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_env:
        path = "/tmp/token.json"
        with open(path, "w") as f:
            f.write(token_env)
        return path
    return "token.json"

def get_credentials_path():
    cred_env = os.environ.get("GOOGLE_CREDS_JSON")
    if cred_env:
        cred_path = "/tmp/credentials.json"
        with open(cred_path, "w") as f:
            f.write(cred_env)
        return cred_path
    return "credentials.json"

def get_drive_service():
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = None
    cred_path = get_credentials_path()
    token_path = get_token_path()
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if os.environ.get("FLASK_ENV") == "production" or os.environ.get("RENDER"):
            raise Exception("Token inválido ou ausente em produção. Gere token.json localmente e configure em GOOGLE_TOKEN_JSON.")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def parse_date_from_nome(filename):
    m = re.search(r'(\d{2}[a-zç]+?\d{2,4})', filename, re.IGNORECASE)
    if m:
        date_str = m.group(1)
        match = re.match(r"(\d{2})([a-zç]+)(\d{2,4})", date_str, re.IGNORECASE)
        if match:
            day, month_ptbr, year = match.groups()
            month = PORTUGUESE_MONTHS.get(month_ptbr.lower())
            if month:
                if len(year) == 2:
                    year = "20" + year
                return datetime.strptime(f"{day}{month}{year}", "%d%m%Y")
    return None

def find_zip_drive(service, primeiro_nome: str, codigo: str, folder_id: str):
    # Busca arquivos .zip cujo nome contenha o código informado
    query = (
      f"name contains '{codigo}' and '{folder_id}' in parents"
    )
    results = service.files().list(q=query, pageSize=1000, fields="files(id, name)").execute()
    items = results.get('files', [])

    print(f"Arquivos retornados pela query:")
    for item in items:
        print(f" - {item['name']}")

    primeiro_nome_cf = primeiro_nome.strip().casefold()
    padrao_codigo = r'\(' + re.escape(codigo) + r'\)'

    for item in items:
        nome_file = item['name']
        print(f'Checando arquivo: {nome_file}')  # Para debug
        if not nome_file.lower().endswith('.zip'):
            continue
        primeiro_nome_cf = primeiro_nome.strip().casefold()
        nome_file_cf = nome_file.casefold()
        primeiro_nome_normalizado = remover_acentos(primeiro_nome_cf)
        nome_file_normalizado = remover_acentos(nome_file_cf)
        if re.search(rf"\b{re.escape(primeiro_nome_normalizado)}\b", nome_file_normalizado) and re.search(padrao_codigo, nome_file):
            file_date = parse_date_from_nome(nome_file)
            if file_date:
                if datetime.now() - file_date <= timedelta(days=60):
                    return item
                else:
                    return "antigo"
    return None

def _processar_laudo(primeiro_nome, codigo):
    try:
        if not codigo or not primeiro_nome:
            return {"ok": False, "msg": "Informe primeiro nome e código do exame."}
        if STORAGE_PROVIDER == "google_drive":
            service = get_drive_service()
            folder_id = "1RS_EBFRdMQirZbR0sVe79sIt7uU5igHE" # local
          #  folder_id = os.environ.get("GOOGLE_FOLDER_ID", "")
            resultado = find_zip_drive(service, primeiro_nome, codigo, folder_id)
            if resultado == "antigo":
                return {"ok": False, "msg": "Arquivo emitido a mais de 60 dias. Por favor, entre em contato com o Epicentro Curitiba pelos telefones (41)3262.1634 ou (41)9947.9532."}
            if not resultado:
                return {"ok": False, "msg": "Arquivo não encontrado para este nome/código."}
            return {"ok": True, "file_id": resultado['id'], "filename": resultado['name']}
        else:
            return {"ok": False, "msg": "Storage provider não configurado corretamente."}
    except Exception as e:
        return {"ok": False, "msg": f"Erro técnico: {str(e)}"}

def download_zip_drive(service, file_id, tmp_path):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(tmp_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.close()

@app.route("/download/<file_id>")
def download(file_id):
    try:
        service = get_drive_service()
        file_metadata = service.files().get(fileId=file_id, fields="name").execute()
        original_filename = file_metadata.get('name', f'{file_id}.zip')
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        download_zip_drive(service, file_id, tmp_path)
        return send_file(tmp_path, as_attachment=True, download_name=original_filename)
    except Exception as e:
        return f"Erro ao baixar laudo: {e}", 500

@app.route("/laudos", methods=["GET", "POST"])
def laudos():
    erro, link = None, None
    if request.method == "POST":
        primeiro_nome = request.form.get("primeiro_nome", "").strip()
        codigo = request.form.get("codigo", "").strip()
        resp = _processar_laudo(primeiro_nome, codigo)
        if resp.get("ok"):
            link = f"/download/{resp.get('file_id')}"
        else:
            link = None
        erro = None if resp.get("ok") else resp.get("msg")
    return render_template_string(HTML, erro=erro, link=link)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
