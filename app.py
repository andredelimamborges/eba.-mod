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
# STREAMLIT CONFIG
# =========================
st.set_page_config(
    page_title="Elder Brain Analytics",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 Elder Brain Analytics")
st.caption("Avaliação comportamental avançada para tomada de decisão em RH")


# =========================
# FORM
# =========================
with st.form("eba_form"):
    col1, col2 = st.columns(2)
    with col1:
        email_analista = st.text_input("E-mail do Analista", placeholder="analista@empresa.com")
    with col2:
        cargo = st.text_input("Cargo Avaliado", placeholder="Ex: Engenheiro de Software Pleno")

    uploaded_file = st.file_uploader(
        "Upload do relatório BFA (PDF ou TXT)",
        type=["pdf", "txt"],
    )

    submitted = st.form_submit_button("Processar Relatório")


# =========================
# PROCESSAMENTO (1x)
# =========================
if submitted:
    if not uploaded_file or not cargo.strip():
        st.error("Informe o cargo e envie o relatório.")
        st.stop()

    texto = extract_text_from_pdf(uploaded_file)
    if not texto.strip():
        st.error("Não foi possível extrair texto do relatório.")
        st.stop()

    empresa_match = re.search(r"(empresa|organização|companhia)\s*[:\-]\s*(.+)", texto, re.I)
    empresa = limpar_nome_empresa(empresa_match.group(2)) if empresa_match else ""

    tracker = UsageTracker(
        provider="groq",
        email=email_analista or "",
        empresa=empresa,
        cargo=cargo,
    )

    with st.spinner("Extraindo dados do relatório..."):
        bfa_data = run_extracao(text=texto, cargo=cargo, tracker=tracker)

    with st.spinner("Analisando perfil comportamental..."):
        analysis = run_analise(bfa_data=bfa_data, cargo=cargo, tracker=tracker)

    # gera PDF apenas uma vez
    with st.spinner("Gerando relatório PDF..."):
        pdf_bytes = gerar_pdf_corporativo(bfa_data, analysis, cargo)

    st.session_state["pdf_bytes"] = pdf_bytes
    st.session_state["bfa_data"] = bfa_data
    st.session_state["analysis"] = analysis

    # envia e-mail (PDF + planilha)
    send_usage_excel_if_configured(
        tracker=tracker,
        email_analista=email_analista,
        cargo=cargo,
    )


# =========================
# DASHBOARD (SEMPRE VISÍVEL APÓS PROCESSAMENTO)
# =========================
if "analysis" in st.session_state:
    analysis = st.session_state["analysis"]
    bfa_data = st.session_state["bfa_data"]

    st.divider()
    st.header("📊 Dashboard Analítico")

    tabs = st.tabs([
        "🎯 Big Five",
        "💼 Competências",
        "🧘 Saúde Emocional",
        "📈 Desenvolvimento",
        "📄 Dados Brutos",
    ])

    # 🎯 Big Five
    with tabs[0]:
        traits = bfa_data.get("traits_bfa", {})
        for k, v in traits.items():
            if v is not None:
                st.metric(k, f"{float(v):.1f}/10")

    # 💼 Competências
    with tabs[1]:
        for c in bfa_data.get("competencias_ms", []):
            st.write(f"**{c.get('nome')}** — Nota: {c.get('nota')} ({c.get('classificacao')})")

    # 🧘 Saúde Emocional
    with tabs[2]:
        saude = bfa_data.get("indicadores_saude_emocional", {})
        for k, v in saude.items():
            if v is not None:
                st.metric(k.replace("_", " ").capitalize(), f"{int(v)} / 100")

    # 📈 Desenvolvimento
    with tabs[3]:
        st.subheader("Pontos Fortes")
        for p in bfa_data.get("pontos_fortes", []):
            st.write(f"• {p}")

        st.subheader("Pontos de Atenção")
        for p in bfa_data.get("pontos_atencao", []):
            st.write(f"• {p}")

        st.subheader("Recomendações")
        for r in analysis.get("recomendacoes_desenvolvimento", []):
            st.write(f"• {r}")

        st.subheader("Cargos Alternativos")
        for c in analysis.get("cargos_alternativos", []):
            st.write(f"• **{c.get('cargo')}** — {c.get('justificativa')}")

    # 📄 Dados Brutos
    with tabs[4]:
        st.json(bfa_data)

    st.divider()

    st.download_button(
        "📄 Baixar Relatório em PDF",
        data=st.session_state["pdf_bytes"],
        file_name=f"EBA_Relatorio_{cargo.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.pdf",
        mime="application/pdf",
        key="download_pdf_final",
    )
