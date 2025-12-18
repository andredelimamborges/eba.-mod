# eba_config.py
from __future__ import annotations

import json
from typing import Dict, Any

# ---------------------------------------------------------
# METADADOS DO APP
# ---------------------------------------------------------
APP_NAME = "Elder Brain Analytics"
APP_VERSION = "12.4 PRO"
APP_TAGLINE = "Avaliações comportamentais com inteligência analítica"

# ---------------------------------------------------------
# CONFIG LLM (mantemos compatível com OpenAI, usando Groq no front)
# ---------------------------------------------------------
DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL_ID = "openai/gpt-oss-20bs"

# ✅ Aliases de compatibilidade (evita ImportError entre versões/módulos)
# Alguns módulos/históricos usam LLM_PROVIDER/LLM_MODEL_ID
LLM_PROVIDER = DEFAULT_PROVIDER
LLM_MODEL_ID = DEFAULT_MODEL_ID

# tokens fixos para segurança (prod-safe)
MAX_TOKENS_FIXED = 3000
TEMP_FIXED = 0.1

# ✅ limites de payload para reduzir 429/timeout e custo (centralizado)
# (o projeto já “corta” textos em outros pontos; aqui vira padrão oficial)
MAX_INPUT_TEXT_CHARS = 10_000
MAX_TRAINING_CONTEXT_CHARS = 3_000

# ---------------------------------------------------------
# TABELA DE PREÇOS (GPT – usada para cálculo administrativo)
# ---------------------------------------------------------
# você pode ajustar aqui quando quiser recalibrar o custo interno
GPT_PRICE_INPUT_PER_1K = 0.010   # US$ por 1k tokens de prompt
GPT_PRICE_OUTPUT_PER_1K = 0.030  # US$ por 1k tokens de completion

# ---------------------------------------------------------
# PERFIL DO CARGO (GERAÇÃO DINÂMICA)
# ---------------------------------------------------------

def gerar_perfil_cargo_dinamico(cargo: str) -> Dict[str, Any]:
    """
    Gera um perfil ideal de competências e Big Five com base no nome do cargo.
    Isso evita precisar armazenar um banco de perfis e permite generalização.

    Você pode expandir esse dicionário conforme quiser.
    """

    cargo = (cargo or "").lower()

    # regras simples (podem ser expandidas)
    if "engenheiro" in cargo or "software" in cargo or "dev" in cargo or "programador" in cargo:
        return {
            "traits_ideais": {
                "Abertura": (6, 9),
                "Conscienciosidade": (7, 10),
                "Extroversão": (2, 6),
                "Amabilidade": (4, 8),
                "Neuroticismo": (1, 4),
            },
            "competencias_criticas": [
                "Resolução de Problemas",
                "Pensamento Analítico",
                "Trabalho em Equipe",
                "Autonomia",
                "Gestão de Tempo",
            ],
        }

    if "vendas" in cargo or "comercial" in cargo or "account" in cargo:
        return {
            "traits_ideais": {
                "Abertura": (5, 8),
                "Conscienciosidade": (6, 9),
                "Extroversão": (7, 10),
                "Amabilidade": (5, 9),
                "Neuroticismo": (1, 4),
            },
            "competencias_criticas": [
                "Comunicação Persuasiva",
                "Negociação",
                "Gestão de Relacionamento",
                "Resiliência",
            ],
        }

    if "lider" in cargo or "coord" in cargo or "gerente" in cargo or "head" in cargo:
        return {
            "traits_ideais": {
                "Abertura": (5, 9),
                "Conscienciosidade": (7, 10),
                "Extroversão": (6, 9),
                "Amabilidade": (5, 9),
                "Neuroticismo": (1, 4),
            },
            "competencias_criticas": [
                "Liderança Servidora",
                "Visão Estratégica",
                "Gestão de Pessoas",
                "Tomada de Decisão sob Pressão",
            ],
        }

    # fallback genérico
    return {
        "traits_ideais": {
            "Abertura": (4, 8),
            "Conscienciosidade": (5, 9),
            "Extroversão": (3, 7),
            "Amabilidade": (4, 8),
            "Neuroticismo": (1, 5),
        },
        "competencias_criticas": [
            "Organização",
            "Trabalho em Equipe",
            "Responsabilidade",
        ],
    }


# ---------------------------------------------------------
# EXPORTAR PERFIL EM JSON (utilitário opcional)
# ---------------------------------------------------------

def exportar_perfil_json(cargo: str) -> str:
    """Exporta o perfil gerado em formato JSON para debug ou testes."""
    perfil = gerar_perfil_cargo_dinamico(cargo)
    return json.dumps(perfil, ensure_ascii=False, indent=2)
