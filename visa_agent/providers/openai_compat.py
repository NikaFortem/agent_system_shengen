import json
import os

from openai import OpenAI


class OpenAICompatProvider:
    """OpenAI-совместимый API: tools / tool_calls, arguments — строка JSON, результат — роль tool."""

    def __init__(self, model: str, base_url: str | None = None):
        self.model = model
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=base_url)

    def _msg(self, m):
        if m["role"] == "assistant" and m.get("tool_calls"):
            return {"role": "assistant", "content": m.get("content"),
                    "tool_calls": [{"id": c["id"], "type": "function",
                                    "function": {"name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                                   for c in m["tool_calls"]]}
        if m["role"] == "tool":
            return {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
        return {"role": m["role"], "content": m["content"]}

    def chat(self, messages, tools):
        r = self.client.chat.completions.create(
            model=self.model, messages=[self._msg(m) for m in messages],
            tools=[{"type": "function", "function": t} for t in tools], timeout=60)
        msg = r.choices[0].message
        calls = []
        for c in msg.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = c.function.arguments          # пусть execute_tool вернёт validation
            calls.append({"id": c.id, "name": c.function.name, "arguments": args})
        return {"content": msg.content, "tool_calls": calls}
