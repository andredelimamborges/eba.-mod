
from __future__ import annotations
import os
from typing import Any, Dict, List

from pdfminer.high_level import extract_text

APP_NAME = "Elder Brain Analytics — Corporate"
APP_VERSION = "V9.1-PROD"
APP_TAGLINE = "Relatório de Análise Comportamental com auxílio de IA"


TRAINING_DIR = "training_data"
PROCESSED_DIR = "relatorios_processados"
os.makedirs(TRAINING_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)


MODELOS_SUGERIDOS_GROQ = [
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "llama-3.2-1b-preview",
    "llama-3.2-3b-preview",
]
MODELOS_SUGERIDOS_OPENAI = ["gpt-4o-mini", "gpt-4o"]

MAX_TOKENS_FIXED = 4096
TEMP_FIXED = 0.3


GPT_PRICE_INPUT_PER_1K = 0.005
GPT_PRICE_OUTPUT_PER_1K = 0.015


DARK_CSS = """
<style>
:root{
  --bg:#20152b; --panel:#2a1f39; --panel-2:#332447; --accent:#9b6bff;
  --text:#EAE6F5; --muted:#B9A8D9; --success:#2ECC71; --warn:#F39C12; --danger:#E74C3C;
}
html, body, .stApp { background: var(--bg); color: var(--text) !important; }
section[data-testid="stSidebar"] { background: #1b1c25; border-right: 1px solid #3b3d4b; }
header[data-testid="stHeader"] { display:none !important; }
.kpi-card{background:var(--panel); border:1px solid #3f4151; border-radius:14px; padding:14px; box-shadow:0 8px 24px rgba(0,0,0,.22)}
.small{color:var(--muted);font-size:.9rem}
.badge{display:inline-block;background:#2a2b36;color:var(--muted);padding:.25rem .55rem;border-radius:999px;border:1px solid #3f4151;margin-right:.35rem}
.stButton>button,.stDownloadButton>button{background:linear-gradient(135deg,var(--accent),#7c69d4); color:white; border:0; padding:.55rem 1rem; border-radius:12px; font-weight:700; box-shadow:0 10px 22px rgba(96,81,155,.25)}
.stButton>button:hover,.stDownloadButton>button:hover{filter:brightness(1.06)}
</style>
"""


def gerar_perfil_cargo_dinamico(cargo: str) -> Dict[str, Any]:
    """Perfil ideal genérico para o cargo informado."""
    return {
        "traits_ideais": {
            "Abertura": (5, 8),
            "Conscienciosidade": (6, 9),
            "Extroversão": (4, 8),
            "Amabilidade": (5, 8),
            "Neuroticismo": (0, 5),
        },
        "competencias_criticas": [
            "Adaptabilidade",
            "Comunicação",
            "Trabalho em Equipe",
            "Resolução de Problemas",
        ],
        "descricao": f"Perfil para {cargo}",
    }


def extract_pdf_text_bytes(file) -> str:
   
    try:
        return extract_text(file)
    except Exception as e:
        return f"[ERRO_EXTRACAO_PDF] {e}"


def load_all_training_texts() -> str:
    
    texts: List[str] = []
    for fname in sorted(os.listdir(TRAINING_DIR)):
        path = os.path.join(TRAINING_DIR, fname)
        try:
            if fname.lower().endswith(".pdf"):
                with open(path, "rb") as f:
                    txt = extract_text(f)
            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
            texts.append(f"--- {fname} ---\n{txt[:2000]}\n")
        except Exception:
            continue
    return "\n".join(texts)
