from __future__ import annotations

import re
from datetime import datetime

import streamlit as st

from eba_reports import (
    criar_radar_bfa,
    criar_grafico_competencias,
    criar_gauge_fit,
    gerar_pdf_corporativo,
)
from eba_config import gerar_perfil_cargo_dinamico
from eba_utils import (
    extract_text_from_pdf,
    limpar_nome_empresa,
    UsageTracker,
    send_usage_excel_if_configured,
    send_report_email_if_configured,
)
from eba_llm import run_extracao, run_analise


# ======================================================
# FUNÇÕES AUXILIARES
# ======================================================
def interpretar_big_five(nome, valor):
    v = float(valor)
    if nome == "Neuroticismo":
        if v <= 4.5:
            return "nível saudável → boa regulação emocional."
        elif v <= 6:
            return "nível moderado → atenção situacional."
        return "nível elevado → risco emocional."

    if v < 4.5:
        return "nível baixo → ponto de desenvolvimento."
    elif v < 6.5:
        return "nível moderado → equilíbrio natural."
    return "nível alto → força clara nesse traço."


def classificar_competencias(lista):
    fortes, criticas = [], []
    for c in lista:
        try:
            nota = float(c.get("nota", 0))
        except Exception:
            continue
        nome = c.get("nome", "")
        if nota >= 55:
            fortes.append(nome)
        elif nota < 45:
            criticas.append(nome)
    return fortes, criticas


# ======================================================
# CONFIG UI
# ======================================================
st.set_page_config(page_title="Elder Brain Analytics", page_icon="🧠", layout="wide")
st.title("🧠 Elder Brain Analytics")
st.caption("Avaliação comportamental avançada para tomada de decisão em RH")


# ======================================================
# FORMULÁRIO
# ======================================================
with st.form("eba_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        email_analista = st.text_input("E-mail do Analista", placeholder="analista@empresa.com")
    with col2:
        cargo_input = st.text_input("Cargo Avaliado", placeholder="Ex: Engenheiro de Software Pleno")
    with col3:
        empresa_input = st.text_input("Empresa", placeholder="Ex: MS Solutions")

    uploaded_file = st.file_uploader(
        "Upload do relatório BFA (PDF ou TXT)", type=["pdf", "txt"]
    )
    submitted = st.form_submit_button("Processar Relatório")


# ======================================================
# PROCESSAMENTO PRINCIPAL
# ======================================================
if submitted:
    if not uploaded_file or not cargo_input.strip():
        st.error("Informe o cargo e envie o relatório.")
        st.stop()

    # 1) extrair texto
    texto = extract_text_from_pdf(uploaded_file)
    if not texto.strip():
        st.error("Não foi possível extrair texto do relatório.")
        st.stop()

    # 2) empresa (input tem prioridade)
    empresa = limpar_nome_empresa(empresa_input) if empresa_input else ""
    if not empresa:
        empresa_match = re.search(
            r"(empresa|organização|companhia)\s*[:\-]\s*(.+)",
            texto,
            re.I,
        )
        empresa = limpar_nome_empresa(empresa_match.group(2)) if empresa_match else ""

    # 3) tracker
    tracker = UsageTracker(
        provider="groq",
        email=email_analista or "",
        empresa=empresa,
        cargo=cargo_input,
    )

    # 4) extração
    with st.spinner("Extraindo dados do relatório..."):
        bfa_data = run_extracao(text=texto, cargo=cargo_input, tracker=tracker)

        if empresa:
            bfa_data["empresa"] = empresa
            if "candidato" not in bfa_data or not isinstance(bfa_data["candidato"], dict):
                bfa_data["candidato"] = {}
            bfa_data["candidato"]["empresa"] = empresa

    # 5) análise
    with st.spinner("Analisando perfil comportamental..."):
        analysis = run_analise(bfa_data=bfa_data, cargo=cargo_input, tracker=tracker)

    # 6) pdf
    with st.spinner("Gerando relatório PDF..."):
        pdf_buf = gerar_pdf_corporativo(bfa_data, analysis, cargo_input)

    pdf_bytes = pdf_buf.getvalue() if hasattr(pdf_buf, "getvalue") else bytes(pdf_buf)

    # 7) sessão
    st.session_state["analysis"] = analysis
    st.session_state["bfa_data"] = bfa_data
    st.session_state["pdf_bytes"] = pdf_bytes
    st.session_state["cargo"] = cargo_input

    # 8) e-mails
    send_usage_excel_if_configured(tracker, email_analista, cargo_input)
    send_report_email_if_configured(tracker, email_analista, cargo_input, pdf_bytes)


# ======================================================
# DASHBOARD
# ======================================================
if "analysis" in st.session_state and "bfa_data" in st.session_state:
    analysis = st.session_state["analysis"]
    bfa_data = st.session_state["bfa_data"]
    cargo = st.session_state.get("cargo", "")

    st.divider()
    st.header("📊 Dashboard Analítico — Elder Brain")

    perfil = gerar_perfil_cargo_dinamico(cargo)
    traits_ideais = (perfil or {}).get("traits_ideais", {})

    tabs = st.tabs(
        ["🎯 Perfil Big Five", "💼 Competências", "🧘 Saúde Emocional", "📈 Desenvolvimento", "📄 Dados Brutos"]
    )

    with tabs[0]:
        traits = bfa_data.get("traits_bfa", {}) or {}
        ordem = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]
        for k in ordem:
            v = traits.get(k)
            if v is not None:
                st.write(f"• **{k} ({float(v):.1f}/10)**: {interpretar_big_five(k, v)}")
        st.plotly_chart(criar_radar_bfa(traits, traits_ideais), use_container_width=True)

    with tabs[1]:
        competencias = bfa_data.get("competencias_ms", []) or []
        fortes, criticas = classificar_competencias(competencias)
        for f in fortes:
            st.write(f"✅ {f}")
        for c in criticas:
            st.write(f"⚠️ {c}")
        fig = criar_grafico_competencias(competencias)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

    with tabs[2]:
        saude = bfa_data.get("indicadores_saude_emocional", {}) or {}
        for k, v in saude.items():
            st.write(f"• {k}: {v}")
        st.plotly_chart(
            criar_gauge_fit((analysis or {}).get("compatibilidade_geral", 0)),
            use_container_width=True,
        )

    with tabs[3]:
        for r in (analysis or {}).get("recomendacoes_desenvolvimento", []):
            st.write(f"• {r}")

    with tabs[4]:
        st.json(bfa_data)

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            "📄 Baixar Relatório em PDF",
            data=st.session_state["pdf_bytes"],
            file_name=f"EBA_Relatorio_{cargo.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.pdf",
            mime="application/pdf",
        )
