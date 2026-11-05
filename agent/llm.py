"""Model clients. Every client returns a Completion with token counts."""
import json
import time
import urllib.request
from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float = 0.0


class OllamaClient:
    def __init__(self, model: str, host: str = "http://127.0.0.1:11434",
                 temperature: float = 0.0, seed: int = 0, num_ctx: int = 16384,
                 timeout_s: int = 600):
        self.model, self.host, self.timeout_s = model, host, timeout_s
        self.options = {"temperature": temperature, "seed": seed, "num_ctx": num_ctx}

    def complete(self, system: str, user: str, json_schema: dict | None = None) -> Completion:
        return self.chat([{"role": "system", "content": system},
                          {"role": "user", "content": user}], json_schema)

    def chat(self, messages: list[dict], json_schema: dict | None = None) -> Completion:
        body = {
            "model": self.model,
            "stream": False,
            "options": self.options,
            "messages": messages,
        }
        if json_schema:
            body["format"] = json_schema
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            out = json.load(resp)
        n_in = out.get("prompt_eval_count", 0)
        if n_in >= self.options["num_ctx"]:
            # Ollama silently truncates prompts past num_ctx.
            raise RuntimeError(f"prompt of {n_in} tokens hit num_ctx")
        return Completion(out["message"]["content"], n_in, out.get("eval_count", 0),
                          time.perf_counter() - start)


def make_client(cfg: dict):
    if cfg["provider"] == "ollama":
        return OllamaClient(cfg["model"], **cfg.get("options", {}))
    raise ValueError(f"unknown provider {cfg['provider']}")
