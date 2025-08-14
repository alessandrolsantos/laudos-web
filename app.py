import os, re, tempfile
from flask import Flask, request, jsonify, render_template_string
import dropbox
from dropbox.exceptions import ApiError
import PyPDF2

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>Consulta de Laudo</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root { font-family: system-ui, Arial, sans-serif; }
    body { background:#f6f7fb; padding: 24px; }
    .card { max-width:420px; margin:40px auto; background:#fff; padding:24px; border-radius:14px; box-shadow:0 10px 30px rgba(0,0,0,.06);}
    h1 { margin:0 0 12px; font-size:22px; }
    p.muted{color:#666; margin-top:0}
    label{display:block; font-size:14px; margin:10px 0 6px;}
    input{width:100%; box-sizing:border-box; padding:12px; border:1px solid #d7d9e0; border-radius:10px; font-size:16px; margin:0;}
    button{width:100%; padding:12px; margin-top:16px; border:0; border-radius:10px; font-size:16px; cursor:pointer; background:#2563eb; color:#fff}
    .error{color:#c02626; background:#fdecec; padding:10px 12px; border-radius:10px; margin-top:14px; font-size:14px}
    .success{background:#ecfdf5; color:#065f46; padding:10px 12px; border-radius:10px; margin-top:14px; font-size:14px}
    a.btn{display:inline-block; margin-top:10px; text-decoration:none; background:#10b981; color:#fff; padding:10px 14px; border-radius:10px}
    small{display:block; margin-top:10px; color:#777}
    /* Aguarde overlay */
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
  </style>
</head>
<body>
  <div id="aguarde-overlay">
    <div>
      <div class="spinner"></div>
      <div id="aguarde-msg">Aguarde, preparando download...</div>
    </div>
  </div>
  <div class="card">
    <h1>Consulta de Laudo</h1>
    <p class="muted">Digite o <b>código do exame</b> e sua <b>data de nascimento</b>.</p>
    <form method="post" novalidate id="laudo-form" autocomplete="off">
      <label for="codigo">Código do exame</label>
      <input id="codigo" name="codigo" required placeholder="Ex.: 123456" autocomplete="off">
      <label for="data_nasc">Data de nascimento</label>
      <input id="data_nasc" name="data_nasc" required placeholder="DD/MM/AAAA" maxlength="10" autocomplete="off">
      <button type="submit">Buscar laudo</button>
    </form>

    {% if erro %}
      <div class="error">❌ {{ erro }}</div>
    {% endif %}
    {% if link %}
      <div class="success">
        ✅ Seu laudo está pronto.
        <div><a class="btn" href="{{ link }}">📄 Baixar laudo</a></div>
        <small>Guarde este link em local seguro.</small>
      </div>
    {% endif %}
  </div>
  <script>
    // Máscara data nascimento
    const dataInput = document.getElementById('data_nasc');
    dataInput.addEventListener('input', function(e) {
      let v = dataInput.value.replace(/\\D/g, '').slice(0,8);
      if (v.length >= 5)
        dataInput.value = v.replace(/(\\d{2})(\\d{2})(\\d{1,4})/, '$1/$2/$3');
      else if (v.length >= 3)
        dataInput.value = v.replace(/(\\d{2})(\\d{1,2})/, '$1/$2');
      else
        dataInput.value = v;
    });

    // Aguarde animado
    document.getElementById('laudo-form').addEventListener('submit', function() {
      document.getElementById('aguarde-overlay').style.display = 'flex';
    });
  </script>
</body>
</html>
"""

def get_dbx():
    return dropbox.Dropbox(
        oauth2_refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
        app_key=os.environ["DROPBOX_APP_KEY"],
        app_secret=os.environ["DROPBOX_APP_SECRET"]
    )

def normalizar_data(data:str)->str:
    data = (data or "").strip().replace("-", "/")
    if re.match(r"\d{2}/\d{2}/\d{2}$", data):
        d,m,y = data.split("/")
        full_year = f"20{y}" if int(y) <= 25 else f"19{y}"
        return f"{d}/{m}/{full_year}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", data)
    if m:
        d,mo,y = m.groups()
        if len(y)==2:
            y = f"20{y}" if int(y) <= 25 else f"19{y}"
        return f"{int(d):02}/{int(mo):02}/{y}"
    return data

def extrair_data_nascimento_pdf(tmp_path:str)->str|None:
    with open(tmp_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        texto = ""
        for page in reader.pages:
            texto += (page.extract_text() or "")
    for pat in [
        r"Data de Nascimento[:\s]*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
        r"Data Nasc[:\s]*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",  # <-- adicionado este padrão
        r"Nascimento[:\s]*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})"
    ]:
        m = re.search(pat, texto, flags=re.IGNORECASE)
        if m:
            return normalizar_data(m.group(1))
    return None

def find_pdf_by_code(dbx, codigo:str, root_folder:str=""):
    codigo = str(codigo).strip()
    res = dbx.files_list_folder(root_folder or "", recursive=True)
    from dropbox.files import FileMetadata
    while True:
        for entry in res.entries:
            if isinstance(entry, FileMetadata) and entry.name.lower().endswith(".pdf"):
                m = re.search(r"\((\w+)\)", entry.name)
                if m and m.group(1) == codigo:
                    return entry
        if res.has_more:
            res = dbx.files_list_folder_continue(res.cursor)
        else:
            break
    return None

def ensure_shared_download_link(dbx, path:str)->str|None:
    try:
        meta = dbx.sharing_create_shared_link_with_settings(path)
        url = meta.url
    except ApiError as e:
        if hasattr(e, "error") and e.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=path)
            url = links.links[0].url if links.links else None
        else:
            raise
    if not url:
        return None
    # forçar download
    if "dl=0" in url:
        url = url.replace("dl=0", "dl=1")
    elif "?dl=1" not in url:
        url += "?dl=1"
    return url

def _processar_laudo(codigo, data_nasc):
    try:
        if not codigo or not data_nasc:
            return {"ok": False, "msg": "Informe código e data de nascimento."}
        dbx = get_dbx()
        root = os.environ.get("DROPBOX_LAUDOS_FOLDER", "")
        entry = find_pdf_by_code(dbx, codigo, root_folder=root)
        if not entry:
            return {"ok": False, "msg": "Laudo não encontrado."}

        # baixa temporariamente para validar a data no conteúdo
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        dbx.files_download_to_file(tmp_path, entry.path_lower)
        data_pdf = extrair_data_nascimento_pdf(tmp_path)
        try: os.remove(tmp_path)
        except: pass

        if not data_pdf:
            return {"ok": False, "msg": "Não foi possível validar a data de nascimento no PDF."}
        if normalizar_data(data_nasc) != data_pdf:
            return {"ok": False, "msg": "Data de nascimento inválida."}

        url = ensure_shared_download_link(dbx, entry.path_lower)
        if not url:
            return {"ok": False, "msg": "Não foi possível gerar o link do laudo."}
        return {"ok": True, "link": url}
    except Exception as e:
        return {"ok": False, "msg": f"Erro técnico: {str(e)}"}

@app.route("/", methods=["GET", "POST"])
def home():
    link = erro = None
    if request.method == "POST":
        codigo = request.form.get("codigo")
        data_nasc = request.form.get("data_nasc")
        resp = _processar_laudo(codigo, data_nasc)
        link = resp.get("link") if resp.get("ok") else None
        erro = None if resp.get("ok") else resp.get("msg")
    return render_template_string(HTML, link=link, erro=erro)

@app.route("/laudo", methods=["POST"])
def laudo():
    data = request.get_json(force=True, silent=True) or {}
    resp = _processar_laudo(data.get("codigo_exame"), data.get("data_nascimento"))
    status = 200 if resp["ok"] else (404 if "não encontrado" in resp["msg"].lower() else 401 if "inválida" in resp["msg"].lower() else 500)
    return jsonify(resp), status

if __name__ == "__main__":
    # Render injeta PORT; localmente cai em 10000
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
