# eba_utils.py
from __future__ import annotations

import os
import re
import time
from typing import Optional

import streamlit as st

try:
    # usado para extrair texto de PDFs
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:
    pdf_extract_text = None  # type: ignore

# pasta onde vamos guardar textos de "treinamento" em segundo plano
TRAINING_DIR = "training_data"


# ================== HELPERS DE ARQUIVO / LAUDO ==================


def extract_pdf_text_bytes(file) -> str:
    """
    Extrai o texto de um PDF a partir de um objeto file-like (ex.: UploadedFile do Streamlit).

    - Usa pdfminer.six se disponível;
    - Garante que o ponteiro do arquivo volta para o início ao final;
    - Em caso de erro, retorna string vazia (e loga um aviso na UI).
    """
    if pdf_extract_text is None:
        st.warning("Biblioteca 'pdfminer.six' não está instalada. PDF não será lido.")
        return ""

    # tenta reposicionar o ponteiro no início
    pos_backup: Optional[int] = None
    try:
        pos_backup = file.tell()
        file.seek(0)
    except Exception:
        pass

    try:
        text = pdf_extract_text(file) or ""
        return text
    except Exception as e:
        st.warning(f"Falha ao extrair texto do PDF: {e}")
        return ""
    finally:
        # devolve o ponteiro para a posição original (se possível)
        try:
            if pos_backup is not None:
                file.seek(pos_backup)
        except Exception:
            pass


def ler_texto_de_arquivo(uploaded_file) -> str:
    """
    Lê o conteúdo textual de um arquivo enviado via Streamlit.

    Regras:
    - Se for PDF (tipo MIME ou extensão), usa extract_pdf_text_bytes.
    - Se for TXT (ou genérico), decodifica bytes como UTF-8 (ignorando erros).
    """
    if uploaded_file is None:
        return ""

    nome = getattr(uploaded_file, "name", "") or ""
    mime = getattr(uploaded_file, "type", "") or ""

    nome_lower = nome.lower()

    # PDF
    if mime == "application/pdf" or nome_lower.endswith(".pdf"):
        return extract_pdf_text_bytes(uploaded_file)

    # Textos simples (txt, csv, etc.)
    try:
        raw = uploaded_file.read()
        # devolve o ponteiro para o início, caso alguém queira reler depois
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        return raw.decode("utf-8", errors="ignore")
    except Exception as e:
        st.warning(f"Falha ao ler arquivo de texto: {e}")
        return ""


# ================== HELPERS DE TREINAMENTO (BACKGROUND) ==================


def _slug(text: str, max_len: int = 40) -> str:
    """
    Converte um texto em um 'slug' seguro para ser usado em nomes de arquivo.
    Ex.: 'Engenheiro de Software Pleno' -> 'engenheiro-de-software-pleno'
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "na"


def ensure_training_dir() -> str:
    """Garante que a pasta de training existe e retorna o caminho."""
    os.makedirs(TRAINING_DIR, exist_ok=True)
    return TRAINING_DIR


def save_training_snippet(
    report_text: str,
    cargo: str,
    empresa: Optional[str] = None,
    max_chars: int = 10000,
) -> None:
    """
    Salva um trecho do laudo como texto de treinamento em segundo plano.

    - Corta o texto em `max_chars` para não ficar enorme.
    - Nome do arquivo inclui timestamp, cargo e empresa (em formato 'slug').
    - Não quebra o app em caso de erro (só loga aviso).
    """
    if not report_text.strip():
        return

    try:
        ensure_training_dir()
        ts = int(time.time())
        slug_cargo = _slug(cargo)
        slug_emp = _slug(empresa or "empresa", max_len=30)
        fname = f"{ts}_{slug_cargo}_{slug_emp}.txt"
        path = os.path.join(TRAINING_DIR, fname)

        snippet = report_text[:max_chars]
        with open(path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(snippet)
    except Exception as e:
        # apenas loga na UI; não é crítico
        st.warning(f"Falha ao salvar snippet de treinamento: {e}")


def load_all_training_texts(
    max_files: int = 50,
    max_chars: int = 40000,
) -> str:
    """
    Lê vários arquivos da pasta `training_data` e devolve um único texto.

    - Limita quantidade de arquivos (`max_files`);
    - Limita tamanho total (`max_chars`) para não explodir o prompt;
    - Se nada existir, retorna string vazia.
    """
    try:
        ensure_training_dir()
        files = sorted(os.listdir(TRAINING_DIR))[:max_files]
        texts = []
        total_chars = 0

        for fname in files:
            path = os.path.join(TRAINING_DIR, fname)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if not content:
                    continue

                # corta se estiver chegando no limite
                remaining = max_chars - total_chars
                if remaining <= 0:
                    break

                chunk = content[:remaining]
                texts.append(f"--- {fname} ---\n{chunk}\n")
                total_chars += len(chunk)
            except Exception:
                continue

        return "\n".join(texts)
    except Exception as e:
        st.warning(f"Falha ao carregar textos de treinamento: {e}")
        return ""
