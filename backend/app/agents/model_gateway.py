"""Configurable model gateway.

LLMs are only used to draft narrative explanations.  They never calculate
business figures, approve actions or execute tools.  The default provider is a
deterministic template so the MVP is reproducible without external credentials.
Every response records the provider actually used, including fallbacks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import settings


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class Narrative:
    text: str
    provider: str
    model: str
    fallback_reason: str | None = None
    task: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "fallback_reason": self.fallback_reason,
            "task": self.task,
        }


class ModelGateway:
    property_descriptions = {
        "bi_narrative": "business performance interpretation",
        "decision_rationale": "decision rationale",
        "audit_narrative": "independent audit commentary",
        "report_narrative": "executive report commentary",
        "excel_explanation": "Excel conversion explanation",
    }

    async def narrate(
        self,
        task: str,
        context: dict[str, Any],
        *,
        deterministic_text: str,
        system_prompt: str | None = None,
        max_tokens: int = 500,
    ) -> Narrative:
        provider = settings.llm_provider
        if provider == "deterministic" or not deterministic_text:
            return Narrative(text=deterministic_text, provider="deterministic", model="template-v1", task=task)

        prompt = self._build_prompt(task, context)
        system = system_prompt or (
            "You are a senior business analyst inside an AI Business Twin. "
            "Use ONLY the facts supplied. Never invent, recalculate or estimate numbers. "
            "Do not give instructions to execute actions. Be concise and CFO-ready. "
            "Return 2-4 short paragraphs of plain text."
        )
        try:
            if provider == "openai":
                from langchain_openai import ChatOpenAI

                if not settings.openai_api_key:
                    raise ModelUnavailable("OPENAI_API_KEY is not configured")
                model = ChatOpenAI(
                    model=settings.llm_model,
                    api_key=settings.openai_api_key,
                    temperature=0.1,
                    max_tokens=max_tokens,
                )
                response = await model.ainvoke([("system", system), ("human", prompt)])
                text = getattr(response, "content", str(response)).strip()
            elif provider == "ollama":
                from langchain_ollama import ChatOllama

                model = ChatOllama(
                    model=settings.ollama_model,
                    base_url=settings.ollama_base_url,
                    temperature=0.1,
                    num_predict=max_tokens,
                )
                response = await model.ainvoke([("system", system), ("human", prompt)])
                text = getattr(response, "content", str(response)).strip()
            else:
                raise ModelUnavailable(f"Unknown provider {provider}")
            if not text:
                raise ModelUnavailable("Empty model response")
            return Narrative(text=text, provider=provider, model=self._model_name(provider), task=task)
        except Exception as exc:  # noqa: BLE001 - fallback must never break the workflow
            return Narrative(
                text=deterministic_text,
                provider="deterministic",
                model="template-v1",
                fallback_reason=f"{type(exc).__name__}: {exc}"[:300],
                task=task,
            )

    def _model_name(self, provider: str) -> str:
        return settings.llm_model if provider == "openai" else settings.ollama_model

    def _build_prompt(self, task: str, context: dict[str, Any]) -> str:
        descriptor = self.property_descriptions.get(task, task)
        return (
            f"Task: {descriptor}.\n"
            "The platform has already computed every number deterministically. "
            "Do not add arithmetic, projected figures, names or events not present below.\n\n"
            f"Facts:\n{json.dumps(context, indent=2, default=str)[:12000]}\n\n"
            "Write the narrative only. Do not output JSON or markdown tables."
        )


model_gateway = ModelGateway()
