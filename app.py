# app.py
from __future__ import annotations

import io
import os
import re
import time
from typing import Dict, Any

import streamlit as st
import pandas as pd

from eba_llm import run_extracao, run_analise
from eba_reports import gerar_pdf_corporativo
from eba_utils import (
    extract_text_from_pdf,
    limpar_nome_empresa,
    UsageTracker,
    send_usage_excel_if_configured,
)

# =========================
# CONFIG STREAMLIT
# =========================
st.set_page_config(
    page_title="Elder Brain Analytics",
    layout="wide",
)

st.title("🧠 Elder Brain Analytics")
st.caption("Análise comportamental e apoio estruturado à decisão")

# =========================
# SESSION STATE
# =========================
if "resultado" not in st.session_state:
    st.session_state.resultado = None

if "bfa_data" not in st.session_state:
    st.session_state.bfa_data = None

if "analysis" not in st.session_state:
    st.session_state.analysis = None

if "pdf_buffer" not in st.session_state:
    st.session_state.pdf_buffer = None

# =========================
# FORMULÁRIO
# =========================
with st.form("form_principal"):
    st.subheader("📄 Envio do Laudo")

    uploaded_file = st.file_uploader(
        "Envie o laudo em PDF",
        type=["pdf"],
        accept_multiple_files=False,
    )

    st.subheader("🏢 Dados do Analista / Empresa")

    email_empresarial = st.text_input(
        "Email empresarial *",
        placeholder="nome@empresa.com",
    )

    cargo = st.text_input(
        "Cargo avaliado",
        placeholder="Ex: Engenheiro de Software",
    )

    submitted = st.form_submit_button("🚀 Processar Laudo")

# =========================
# VALIDAÇÕES
# =========================
if submitted:
    if not uploaded_file:
        st.error("Envie um arquivo PDF para continuar.")
        st.stop()

    if not email_empresarial or "@" not in email_empresarial:
        st.error("Informe um email empresarial válido.")
        st.stop()

    if not cargo:
        st.error("Informe o cargo avaliado.")
        st.stop()

    # =========================
    # EXTRAÇÃO DO PDF
    # =========================
    with st.spinner("📥 Extraindo informações do laudo..."):
        try:
            laudo_texto = extract_text_from_pdf(uploaded_file)
        except Exception as e:
            st.error(f"Falha ao extrair texto do PDF: {e}")
            st.stop()

    # tenta extrair empresa do texto
    empresa_raw = ""
    empresa_match = re.search(
        r"(empresa|organização|companhia)\s*[:\-]\s*(.+)",
        laudo_texto,
        re.IGNORECASE,
    )
    if empresa_match:
        empresa_raw = empresa_match.group(2)

    empresa = limpar_nome_empresa(empresa_raw)

    # =========================
    # TRACKER DE USO
    # =========================
    tracker = UsageTracker(
        provider="groq",
        email=email_empresarial,
        empresa=empresa,
        cargo=cargo,
    )

    # =========================
    # EXTRAÇÃO LLM
    # =========================
    with st.spinner("🧠 Interpretando o laudo (extração estruturada)..."):
        try:
            bfa_data = run_extracao(
                text=laudo_texto,
                tracker=tracker,
            )
        except Exception as e:
            st.error(f"Falha na etapa de extração: {e}")
            st.stop()

    # =========================
    # ANÁLISE LLM
    # =========================
    with st.spinner("📊 Gerando análise comportamental..."):
        try:
            analysis = run_analise(
                bfa_data=bfa_data,
                cargo=cargo,
                tracker=tracker,
            )
        except Exception as e:
            st.error(f"Falha na etapa de análise: {e}")
            st.stop()

    # salva no session_state
    st.session_state.bfa_data = bfa_data
    st.session_state.analysis = analysis

    # =========================
    # GERAR PDF
    # =========================
    with st.spinner("📑 Montando relatório corporativo..."):
        try:
            pdf_buffer = gerar_pdf_corporativo(
                bfa_data=bfa_data,
                analysis=analysis,
                cargo=cargo,
                logo_path=None,
            )
            st.session_state.pdf_buffer = pdf_buffer
        except Exception as e:
            st.error(f"Erro ao gerar PDF: {e}")
            st.stop()

    # =========================
    # ENVIO EXCEL (USO / PREÇO)
    # =========================
    send_usage_excel_if_configured(
        tracker=tracker,
        email_analista=email_empresarial,
        cargo=cargo,
    )

    st.success("✅ Análise concluída com sucesso.")

# =========================
# RESULTADOS (NÃO SOMEM)
# =========================
if st.session_state.bfa_data and st.session_state.analysis:
    st.divider()
    st.subheader("📊 Resultados da Análise")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🎯 Big Five")
        st.write(st.session_state.analysis.get("resumo_big_five", "—"))

        st.markdown("### 💼 Competências")
        st.write(st.session_state.analysis.get("resumo_competencias", "—"))

    with col2:
        st.markdown("### 🧘 Saúde Emocional")
        st.write(st.session_state.analysis.get("saude_emocional_contexto", "—"))

        st.markdown("### 📈 Desenvolvimento")
        recs = st.session_state.analysis.get("recomendacoes_desenvolvimento", [])
        if recs:
            for r in recs:
                st.write(f"- {r}")
        else:
            st.write("—")

    st.markdown("### 📄 Dados Brutos")
    st.json(st.session_state.bfa_data)

# =========================
# DOWNLOAD PDF
# =========================
if st.session_state.pdf_buffer:
    st.divider()
    st.download_button(
        label="⬇️ Baixar Relatório PDF",
        data=st.session_state.pdf_buffer,
        file_name="Relatorio_Elder_Brain_Analytics.pdf",
        mime="application/pdf",
    )
