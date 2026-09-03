import json
from typing import List, Dict, Any, Optional, Tuple
from langchain_ollama import ChatOllama

class ModelAdapter:
    def __init__(self, model_name: str = "llama3.2", base_url: str = "http://localhost:11434", temperature: float = 0.0):
        self.llm = ChatOllama(
                    model=model_name,
                    temperature=temperature,
                    base_url=base_url,
                    num_ctx=2048,
                    #format="json", 
                )

        self.turns_count: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0


    def complete(self, messages:List[Dict[str,str]], tools:Optional[Any] = None):

        formatted_messages = [(msg["role"], msg["content"]) for msg in messages]

        ai_message = self.llm.invoke(formatted_messages)

        self.turns_count += 1

        token_input_count = 0
        token_output_count = 0

        if hasattr(ai_message, "usage_metadata") and ai_message.usage_metadata:
            token_input_count = ai_message.usage_metadata.get("input_tokens",0)
            token_output_count = ai_message.usage_metadata.get("output_tokens",0)
        elif hasattr(ai_message, "response_metadata") and ai_message.response_metadata:
            info = ai_message.response_metadata
            token_input_count = info.get("prompt_eval_count", info.get("token_usage", {}).get("prompt_tokens",0))
            token_output_count = info.get("eval_count", info.get("token_usage", {}).get("completion_tokens",0))

        total_turns = token_input_count + token_output_count

        self.input_tokens += token_input_count
        self.output_tokens += token_output_count

        turns_overview = {
            "input_token_count": token_input_count,
            "output_token_count": token_output_count,
            "total_token_count": total_turns
        }

        model_response = self._parse_and_adapt(ai_message.content)
        return model_response, turns_overview

    def stats_info(self, conversation_history: List[Dict[str,str]]) -> Dict[str,Any]:
        conversation_length = len(json.dumps(conversation_history))

        return {
            "total_turn_count": self. turns_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "length_of_conversation": conversation_length
        }

    def _extract_json(self, raw_text: str):
        start = raw_text.find("{")
        end = raw_text.rfind("}")

        if start != -1 and end != -1 and end > start:
            return raw_text[start: end + 1]
        return raw_text

    def _parse_and_adapt(self, raw_output: str):
        clean_output = self._extract_json(raw_output)

        try:
            data = json.loads(clean_output)
        except json.JSONDecodeError:
            data = {"summary": raw_output.strip(), "tags": []}

        final_tags = []
        final_summary = ""

        for key, value in data.items():
            key_lower = str(key).lower()
            if "tag" in key_lower or isinstance(value, list):
                if isinstance(value, list):
                    final_tags.extend([str(item).strip() for item in value])
                elif isinstance(value, str):
                    final_tags.extend([j.strip() for j in value.split(",")])
            elif "summary" in key_lower or "content" in key_lower or "review " in key_lower:
                final_summary = str(value).strip()

        unique_tags = list(dict.fromkeys(final_tags))

        if not final_summary:
            for k, v in data.items():
                if isinstance(v,str) and "tag" not in str(k).lower():
                    final_summary = v
                    break

        return {
            "tags": unique_tags[:3],
            "summary": final_summary
        }
