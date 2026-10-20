"""TelecomRAGAgent - a small retrieval-augmented agent with a refusal guardrail.

Packaged, reusable definition for the Sandbox Training agent catalog. The heavy
dependencies (an embedding model and an LLM) are *injected*, so this module only
needs numpy and is trivial to test with stubs. The companion notebook
(notebooks/telecom-rag-agent/) shows how to create and test it on TeleQnA.

Tools exposed: retrieve, answer, refuse. Every call is appended to `self.log`,
so the agent's behaviour is auditable.
"""
from __future__ import annotations

import re

import numpy as np


class TelecomRAGAgent:
    """Agent that retrieves context, then answers a multiple-choice question or
    refuses when retrieval confidence is too low.

    Parameters
    ----------
    embedder : object with .encode(list[str], normalize_embeddings=bool) -> np.ndarray
    llm      : callable(prompt, max_new_tokens=int) -> [{"generated_text": str}]
    kb_docs  : list[str]  knowledge-base documents to retrieve from
    tau      : float      refuse when the best cosine similarity is below this
    """

    def __init__(self, embedder, llm, kb_docs, tau: float = 0.25):
        self.embedder = embedder
        self.llm = llm
        self.kb_docs = list(kb_docs)
        self.tau = tau
        self.kb_emb = np.asarray(
            embedder.encode(self.kb_docs, normalize_embeddings=True))
        self.log: list[tuple] = []

    # -- tools ------------------------------------------------------------- #
    def retrieve(self, query: str, k: int = 3):
        q = np.asarray(self.embedder.encode([query], normalize_embeddings=True))[0]
        sims = self.kb_emb @ q
        top = np.argsort(sims)[::-1][:k]
        conf = float(sims[top[0]])
        self.log.append(("retrieve", round(conf, 3)))
        return [self.kb_docs[i] for i in top], conf

    def answer(self, question: str, options: dict, context: str):
        opts = "\n".join(f"{n}) {t}" for n, t in options.items())
        prompt = ("Use the context to answer the telecom multiple-choice question.\n"
                  f"Context:\n{context}\n\nQuestion: {question}\nOptions:\n{opts}\n"
                  "Reply with only the number of the correct option.")
        out = self.llm(prompt, max_new_tokens=5)[0]["generated_text"]
        m = re.search(r"\d+", out)
        pred = int(m.group()) if m and int(m.group()) in options else None
        self.log.append(("answer", pred))
        return pred

    def refuse(self, reason: str = "low retrieval confidence"):
        self.log.append(("refuse", reason))
        return None

    # -- agent loop -------------------------------------------------------- #
    def run(self, question: str, options: dict):
        """Retrieve, then answer or refuse. Returns the chosen option number or None."""
        self.log = []
        context_docs, conf = self.retrieve(
            question + " " + " ".join(map(str, options.values())))
        if conf < self.tau:
            return self.refuse()
        return self.answer(question, options, "\n".join(context_docs))
