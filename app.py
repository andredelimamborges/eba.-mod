# app.py
from __future__ import annotations

import re
from datetime import datetime

import streamlit as st

from eba_utils import (
    extract_text_from_pdf,
    limpar_nome_empresa,
    UsageTracker,
    send_usage_excel_if_configured,
)
from eba_llm import run_extracao, run_analise
from eba_reports import gerar_pdf_corporativo


# =========================
# CONFIG STREAMLIT
# =========================
st.set_page_config(
    page_title="Elder Brain Analytics",
    page_icon="🧠",
    layout="centered",
)

st.title("🧠 Elder Brain Analytics")
st.caption("Avaliação comportamental avançada com suporte de IA")


# =========================
# INPUTS
# =========================
with st.form("eba_form"):
    email_analista = st.text_input("E-mail do Analista", placeholder="analista@empresa.com")
    cargo = st.text_input("Cargo Avaliado", placeholder="Ex: Engenheiro de Software Pleno")
    uploaded_file = st.file_uploader(
        "Upload do relatório BFA (PDF ou TXT)",
        type=["pdf", "txt"],
        accept_multiple_files=False,
    )
    submitted = st.form_submit_button("Processar Relatório")


# =========================
# PROCESSAMENTO
# =========================
if submitted:
    # validações básicas
    if not uploaded_file:
        st.error("Por favor, envie um relatório BFA.")
        st.stop()

    if not cargo.strip():
        st.error("Informe o cargo avaliado.")
        st.stop()

    with st.spinner("Lendo relatório..."):
        texto_laudo = extract_text_from_pdf(uploaded_file)

    if not texto_laudo.strip():
        st.error("Não foi possível extrair texto do relatório.")
        st.stop()

    # tentativa simples de extrair empresa do texto
    empresa_match = re.search(
        r"(empresa|organização|companhia)\s*[:\-]\s*(.+)",
        texto_laudo,
        re.IGNORECASE,
    )
    empresa_raw = empresa_match.group(2) if empresa_match else ""
    empresa = limpar_nome_empresa(empresa_raw)

    # tracker único da execução
    tracker = UsageTracker(
        provider="groq",
        email=email_analista or "",
        empresa=empresa,
        cargo=cargo,
    )

    try:
        with st.spinner("Extraindo dados estruturados do relatório..."):
            bfa_data = run_extracao(
                text=texto_laudo,
                cargo=cargo,
                tracker=tracker,
            )

        with st.spinner("Realizando análise comportamental e fit para o cargo..."):
            analysis = run_analise(
                bfa_data=bfa_data,
                cargo=cargo,
                tracker=tracker,
            )

    except Exception as e:
        st.error(f"Erro durante o processamento: {e}")
        st.stop()

    # =========================
    # RESULTADOS
    # =========================
    st.success("Análise concluída com sucesso.")

    st.subheader("📌 Decisão Geral")
    st.write(analysis.get("decisao", "N/A"))
    st.metric(
        "Compatibilidade com o Cargo",
        f"{int(analysis.get('compatibilidade_geral', 0))}%",
    )

    st.subheader("📝 Resumo Executivo")
    st.write(analysis.get("resumo_executivo", "Resumo não disponível."))

    # =========================
    # PDF
    # =========================
    with st.spinner("Gerando PDF corporativo..."):
        pdf_bytes = gerar_pdf_corporativo(
            bfa_data=bfa_data,
            analysis=analysis,
            cargo=cargo,
        )

    st.download_button(
        "📄 Baixar Relatório em PDF",
        data=pdf_bytes,
        file_name=f"EBA_Relatorio_{cargo.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.pdf",
        mime="application/pdf",
    )

    # =========================
    # USO / FINANCEIRO
    # =========================
    send_usage_excel_if_configured(
        tracker=tracker,
        email_analista=email_analista,
        cargo=cargo,
    )

    # debug opcional (desativado por padrão)
    with st.expander("🔎 Detalhes Técnicos (Uso de Tokens)"):
        st.json(tracker.dict())
        st.write(f"Custo estimado (tabela GPT): ${tracker.cost_usd_gpt():.4f}")
