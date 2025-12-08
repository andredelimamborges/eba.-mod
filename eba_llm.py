# eba_llm.py
from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
import streamlit as st

from eba_config import (
    MAX_TOKENS_FIXED,
    TEMP_FIXED,
    GPT_PRICE_INPUT_PER_1K,
    GPT_PRICE_OUTPUT_PER_1K,
)

# libs opcionais
try:
    import tiktoken
except Exception:
    tiktoken = None  # type: ignore

try:
    from groq import Groq
except Exception:
    Groq = None  # type: ignore

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


# ======== Token Accounting ========
@dataclass
class TokenStep:
    prompt: int = 0
    completion: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion


@dataclass
class TokenTracker:
    steps: Dict[str, TokenStep] = field(
        default_factory=lambda: {
            "extracao": TokenStep(),
            "analise": TokenStep(),
            "chat": TokenStep(),
            "pdf": TokenStep(),
        }
    )
    model: str = ""
    provider: str = ""

    def add(self, step: str, prompt_tokens: int, completion_tokens: int) -> None:
        if step not in self.steps:
            self.steps[step] = TokenStep()
        self.steps[step].prompt += int(prompt_tokens or 0)
        self.steps[step].completion += int(completion_tokens or 0)

    def dict(self) -> Dict[str, Dict[str, int]]:
        return {
            k: {"prompt": v.prompt, "completion": v.completion, "total": v.total}
            for k, v in self.steps.items()
        }

    @property
    def total_prompt(self) -> int:
        return sum(s.prompt for s in self.steps.values())

    @property
    def total_completion(self) -> int:
        return sum(s.completion for s in self.steps.values())

    @property
    def total_tokens(self) -> int:
        return self.total_prompt + self.total_completion

    def cost_usd_gpt(self) -> float:
        return (self.total_prompt / 1000.0) * GPT_PRICE_INPUT_PER_1K + (
            self.total_completion / 1000.0
        ) * GPT_PRICE_OUTPUT_PER_1K


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        if tiktoken:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
    except Exception:
        pass
    return max(1, int(len(text) / 4))


@st.cache_resource(show_spinner=False)
def get_llm_client_cached(provider: str, api_key: str):
    """Cria cliente LLM seguro (Groq/OpenAI), ajustando proxies."""
    if not api_key:
        raise RuntimeError("Chave da API não configurada. Defina nos Secrets do Streamlit.")
    pv = (provider or "Groq").lower()

    for var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        os.environ.pop(var, None)

    if pv == "groq":
        if Groq is None:
            raise RuntimeError("SDK Groq não instalado.")
        try:
            client = Groq(api_key=api_key, http_client=httpx.Client(proxies=None))
            return client
        except Exception as e:
            raise RuntimeError(f"[Erro cliente] Groq SDK falhou ({e})")

    if pv == "openai":
        if OpenAI is None:
            raise RuntimeError("SDK OpenAI não instalado.")
        try:
            client = OpenAI(api_key=api_key, http_client=httpx.Client(proxies=None))
            return client
        except Exception as e:
            raise RuntimeError(f"[Erro cliente] OpenAI SDK falhou ({e})")

    raise RuntimeError(f"Provedor não suportado: {provider}")


def get_api_key_for_provider(provider: str) -> str:
    provider = (provider or "Groq").lower()
    if provider == "groq":
        key = st.secrets.get("GROQ_API_KEY", "")
        if not key:
            raise RuntimeError("GROQ_API_KEY não configurada nos Secrets do Streamlit.")
        return key
    if provider == "openai":
        key = st.secrets.get("OPENAI_API_KEY", "")
        if not key:
            raise RuntimeError("OPENAI_API_KEY não configurada nos Secrets do Streamlit.")
        return key
    raise RuntimeError(f"Provedor não suportado: {provider}")


# ======== PROMPTS ========
EXTRACTION_PROMPT = """Você é um especialista em análise de relatórios BFA (Big Five Analysis) para seleção de talentos.
Sua tarefa: extrair dados do relatório abaixo e retornar APENAS um JSON válido, sem texto adicional.

ESTRUTURA OBRIGATÓRIA:
{
  "candidato": {"nome": "string ou null","cargo_avaliado": "string ou null"},
  "traits_bfa": {
    "Abertura": número 0-10 ou null,
    "Conscienciosidade": número 0-10 ou null,
    "Extroversao": número 0-10 ou null,
    "Amabilidade": número 0-10 ou null,
    "Neuroticismo": número 0-10 ou null
  },
  "competencias_ms": [{"nome": "string","nota": número,"classificacao": "string"}],
  "facetas_relevantes": [{"nome": "string","percentil": número,"interpretacao": "string resumida"}],
  "indicadores_saude_emocional": {"ansiedade": 0-100 ou null,"irritabilidade": 0-100 ou null,"estado_animo": 0-100 ou null,"impulsividade": 0-100 ou null},
  "potencial_lideranca": "BAIXO" | "MÉDIO" | "ALTO" ou null,
  "integridade_fgi": 0-100 ou null,
  "resumo_qualitativo": "texto original do relatório",
  "pontos_fortes": ["3-5 itens"],
  "pontos_atencao": ["2-4 itens"],
  "fit_geral_cargo": 0-100
}

REGRAS:
1) Normalize percentis; 2) Big Five: percentil 60 -> 6.0/10;
3) Use null quando não houver; 4) fit_geral_cargo 0-100 baseado no cargo: {cargo}.

RELATÓRIO:
\"\"\"{text}\"\"\"

MATERIAIS (opcional):
\"\"\"{training_context}\"\"\"

Retorne apenas o JSON puro.
"""

ANALYSIS_PROMPT = """Você é um consultor sênior de RH especializado em análise comportamental.

Cargo avaliado: {cargo}

DADOS (JSON extraído):
{json_data}

PERFIL IDEAL DO CARGO:
{perfil_cargo}

Responda em JSON:
{
  "compatibilidade_geral": 0-100,
  "decisao": "RECOMENDADO" | "RECOMENDADO COM RESSALVAS" | "NÃO RECOMENDADO",
  "justificativa_decisao": "texto",
  "analise_tracos": {
    "Abertura": "texto","Conscienciosidade": "texto","Extroversao": "texto","Amabilidade": "texto","Neuroticismo": "texto"
  },
  "competencias_criticas": [{"competencia":"nome","avaliacao":"texto","status":"ATENDE" | "PARCIAL" | "NÃO ATENDE"}],
  "saude_emocional_contexto": "texto",
  "recomendacoes_desenvolvimento": ["a","b","c"],
  "cargos_alternativos": [{"cargo":"nome","justificativa":"texto"}],
  "resumo_executivo": "100-150 palavras"
}
"""


def _chat_completion_json(
    provider: str,
    client: Any,
    model: str,
    messages: List[Dict[str, str]],
    force_json: bool = True,
) -> Tuple[str, Optional[Dict[str, int]]]:
    usage: Optional[Dict[str, int]] = None
    pv = (provider or "groq").lower()

    if pv == "groq":
        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=messages,
            max_tokens=MAX_TOKENS_FIXED,
            temperature=TEMP_FIXED,
        )
        if force_json:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content.strip()
        u = getattr(resp, "usage", None)
        if u:
            usage = {
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.total_tokens,
            }
        return content, usage

    # openai
    resp = client.chat.completions.create(
        model=model,
        messages=messages
        if not force_json
        else ([{"role": "system", "content": "Responda apenas com JSON válido."}] + messages),
        temperature=TEMP_FIXED,
        max_tokens=MAX_TOKENS_FIXED,
        response_format={"type": "json_object"} if force_json else None,
    )
    content = resp.choices[0].message.content.strip()
    u = getattr(resp, "usage", None)
    if u:
        usage = {
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "total_tokens": u.total_tokens,
        }
    return content, usage


def _estimate_and_add(
    tracker: TokenTracker,
    step: str,
    messages: List[Dict[str, str]],
    content: str,
    usage: Optional[Dict[str, int]],
) -> None:
    if usage:
        tracker.add(step, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        return
    prompt_text = "\n".join([m.get("content", "") for m in messages])
    tracker.add(step, _estimate_tokens(prompt_text), _estimate_tokens(content))


# ======== CORE: extração / análise / chat ========
def extract_bfa_data(
    text: str,
    cargo: str,
    training_context: str,
    provider: str,
    model_id: str,
    token: str,
    tracker: TokenTracker,
):
    """Etapa 1: extração em JSON estruturado."""
    try:
        client = get_llm_client_cached(provider, token)
    except Exception as e:
        return None, f"[Erro cliente] {e}"

    prompt = (
        EXTRACTION_PROMPT.replace("{text}", text[:10000])
        .replace("{training_context}", training_context[:3000])
        .replace("{cargo}", cargo)
    )

    messages = [{"role": "user", "content": prompt}]
    try:
        content, usage = _chat_completion_json(provider, client, model_id.strip(), messages, True)
        _estimate_and_add(tracker, "extracao", messages, content, usage)

        try:
            return json.loads(content), content
        except Exception:
            m = re.search(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", content, re.DOTALL)
            if m:
                return json.loads(m.group(0)), content
            return None, f"Nenhum JSON válido encontrado: {content[:800]}..."
    except Exception as e:
        return None, f"[Erro LLM] {e}"


def analyze_bfa_data(
    bfa_data: Dict[str, Any],
    cargo: str,
    perfil_cargo: Dict[str, Any],
    provider: str,
    model_id: str,
    token: str,
    tracker: TokenTracker,
):
    """Etapa 2: análise de compatibilidade/fit."""
    try:
        client = get_llm_client_cached(provider, token)
    except Exception as e:
        return None, f"[Erro cliente] {e}"

    prompt = (
        ANALYSIS_PROMPT.replace("{cargo}", cargo)
        .replace("{json_data}", json.dumps(bfa_data, ensure_ascii=False, indent=2))
        .replace("{perfil_cargo}", json.dumps(perfil_cargo, ensure_ascii=False, indent=2))
    )

    messages = [
        {"role": "system", "content": "Responda estritamente em JSON."},
        {"role": "user", "content": prompt},
    ]
    try:
        content, usage = _chat_completion_json(
            provider, client, model_id.strip(), messages, True
        )
        _estimate_and_add(tracker, "analise", messages, content, usage)
        try:
            return json.loads(content), content
        except Exception:
            fix_prompt_msgs = [
                {"role": "system", "content": "Retorne apenas o JSON válido."},
                {"role": "user", "content": f"Converta para JSON válido:\n{content}"},
            ]
            fix, usage2 = _chat_completion_json(
                provider, client, model_id.strip(), fix_prompt_msgs, True
            )
            _estimate_and_add(tracker, "analise", fix_prompt_msgs, fix, usage2)
            return json.loads(fix), fix
    except Exception as e:
        return None, f"[Erro durante análise] {e}"


def chat_with_elder_brain(
    question: str,
    bfa_data: Dict[str, Any],
    analysis: Dict[str, Any],
    cargo: str,
    provider: str,
    model_id: str,
    token: str,
    tracker: TokenTracker,
) -> str:
    """Chat contextualizado com o relatório + análise."""
    try:
        client = get_llm_client_cached(provider, token)
    except Exception as e:
        return f"Erro ao conectar com a IA: {e}"

    contexto = f"""
Você é um consultor executivo de RH analisando um relatório BFA.

DADOS (JSON): {json.dumps(bfa_data, ensure_ascii=False)}
ANÁLISE (JSON): {json.dumps(analysis, ensure_ascii=False)}
CARGO: {cargo}

PERGUNTA: {question}
Responda de forma objetiva e profissional.
""".strip()

    messages = [{"role": "user", "content": contexto}]
    try:
        content, usage = _chat_completion_json(
            provider, client, model_id.strip(), messages, False
        )
        _estimate_and_add(tracker, "chat", messages, content, usage)
        return content
    except Exception as e:
        msg = f"Erro na resposta da IA: {e}"
        if hasattr(e, "response") and getattr(e.response, "text", None):
            msg += f" - Detalhes: {e.response.text}"
        return msg
