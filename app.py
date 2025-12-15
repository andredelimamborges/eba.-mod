# app.py
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
)
from eba_llm import run_extracao, run_analise


# =========================
# HELPERS UI
# =========================
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
        cargo_input = st.text_input("Cargo Avaliado", placeholder="Ex: Engenheiro de Software Pleno")

    uploaded_file = st.file_uploader(
        "Upload do relatório BFA (PDF ou TXT)",
        type=["pdf", "txt"],
    )

    submitted = st.form_submit_button("Processar Relatório")


# =========================
# PROCESSAMENTO
# =========================
if submitted:
    if not uploaded_file or not cargo_input.strip():
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
        cargo=cargo_input,
    )

    with st.spinner("Extraindo dados do relatório..."):
        bfa_data = run_extracao(text=texto, cargo=cargo_input, tracker=tracker)

    with st.spinner("Analisando perfil comportamental..."):
        analysis = run_analise(bfa_data=bfa_data, cargo=cargo_input, tracker=tracker)

    with st.spinner("Gerando relatório PDF..."):
        pdf_bytes = gerar_pdf_corporativo(bfa_data, analysis, cargo_input)

    # persistência segura
    st.session_state["analysis"] = analysis
    st.session_state["bfa_data"] = bfa_data
    st.session_state["pdf_bytes"] = pdf_bytes
    st.session_state["cargo"] = cargo_input

    send_usage_excel_if_configured(
        tracker=tracker,
        email_analista=email_analista,
        cargo=cargo_input,
    )


# =========================
# DASHBOARD (SÓ SE HOUVER DADOS)
# =========================
if "analysis" in st.session_state:
    analysis = st.session_state["analysis"]
    bfa_data = st.session_state["bfa_data"]
    cargo = st.session_state["cargo"]

    st.divider()
    st.header("📊 Dashboard Analítico — Elder Brain")

    perfil = gerar_perfil_cargo_dinamico(cargo)
    traits_ideais = perfil.get("traits_ideais", {})

    tabs = st.tabs([
        "🎯 Perfil Big Five",
        "💼 Competências",
        "🧘 Saúde Emocional",
        "📈 Desenvolvimento",
        "📄 Dados Brutos",
    ])

    # 🎯 BIG FIVE
    with tabs[0]:
        traits = bfa_data.get("traits_bfa", {})
        ordem = ["Abertura", "Conscienciosidade", "Extroversão", "Amabilidade", "Neuroticismo"]

        st.subheader("🎯 Perfil Big Five — Interpretação")
        for k in ordem:
            v = traits.get(k) or traits.get(k.replace("ã", "a").replace("ç", "c"))
            if v is not None:
                st.write(f"• **{k} ({float(v):.1f}/10)**: {interpretar_big_five(k, v)}")

        st.plotly_chart(
            criar_radar_bfa(traits, traits_ideais),
            use_container_width=True,
        )

    # 💼 COMPETÊNCIAS
    with tabs[1]:
        competencias = bfa_data.get("competencias_ms", [])
        fortes, criticas = classificar_competencias(competencias)

        st.subheader("💼 Competências — Leitura Geral")

        if fortes:
            st.markdown("🔹 **Pontos de Força**")
            for f in fortes:
                st.write(f"• {f} — desempenho consistente para o cargo.")

        if criticas:
            st.markdown("🔸 **Pontos Críticos**")
            for c in criticas:
                st.write(f"• {c} — requer acompanhamento e plano de desenvolvimento.")

        fig_comp = criar_grafico_competencias(competencias)
        if fig_comp:
            st.plotly_chart(fig_comp, use_container_width=True)

    # 🧘 SAÚDE EMOCIONAL
    with tabs[2]:
        saude = bfa_data.get("indicadores_saude_emocional", {})

        st.subheader("🧘 Saúde Emocional — Justificativa Completa")
        for k, v in saude.items():
            if v is not None:
                st.write(f"• **{k.replace('_',' ').capitalize()}**: {int(v)}/100 → nível saudável, dentro do esperado.")

        contexto = analysis.get("saude_emocional_contexto", "")
        if contexto:
            st.markdown("**Contextualização da IA**")
            st.write(contexto)

        st.plotly_chart(
            criar_gauge_fit(analysis.get("compatibilidade_geral", 0)),
            use_container_width=True,
        )

    # 📈 DESENVOLVIMENTO
    with tabs[3]:
        st.subheader("📈 Recomendações de Desenvolvimento — Versão Ampliada")

        for i, rec in enumerate(analysis.get("recomendacoes_desenvolvimento", []), 1):
            st.write(f"{i}. {rec}")

        st.markdown("**Sugestões Adicionais (Elder Brain)**")
        st.write("• Treinamentos recomendados: Inteligência Emocional, Comunicação Assertiva, Gestão de Conflitos.")
        st.write("• Rotina sugerida: feedback quinzenal estruturado com liderança.")
        st.write("• Foco de curto prazo: trabalhar competências críticas e traços ligados à resiliência.")

        cargos_alt = analysis.get("cargos_alternativos", [])
        if cargos_alt:
            st.markdown("**Cargos Alternativos Sugeridos**")
            for c in cargos_alt:
                st.write(f"• **{c.get('cargo')}** — {c.get('justificativa')}")

    # 📄 DADOS BRUTOS
    with tabs[4]:
        st.json(bfa_data)

    # DOWNLOAD FORA DAS TABS
    st.download_button(
        "📄 Baixar Relatório em PDF",
        data=st.session_state["pdf_bytes"],
        file_name=f"EBA_Relatorio_{cargo.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.pdf",
        mime="application/pdf",
        key="download_pdf_final",
    )
