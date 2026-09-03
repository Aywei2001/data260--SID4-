
import argparse, json, os, re, sys, time
from typing import List, Dict, Any, Iterable, Tuple
from src.model_client import ModelAdapter


def stats_output(adapter: ModelAdapter, history: List[Dict[str,str]]):
    stats = adapter.stats_info(history)
    print(f"Turn Number: {stats['total_turn_count']}")
    print(f"Input Tokens: {stats['input_tokens']}")
    print(f"Output Tokens: {stats['output_tokens']}")
    print(f"Total Turns: {stats['total_tokens']}")
    print(f"Conversation Length: {stats['length_of_conversation']} characters")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default = os.environ.get("SMOL_MODEL", "llama3.2"))
    parser.add_argument("--temperature", type = float, default = 0.0)
    args = parser.parse_args()

    agent_md_path = "AGENT.md"

    if os.path.exists(agent_md_path):
        with open(agent_md_path, "r", encoding = "utf-8") as f:
            system_instruction = f.read()
    else:
        system_instruction = "You are reviewing code. Respond in JSON using 'tags' and 'summary' "

    adapter = ModelAdapter(model_name = args.model, temperature = args.temperature)

    prompts: List[str] = [
        "Turn 1: Review x = 3 + 12",
        "Turn 2: Review print('Hello' + name)",
        "Turn 3: Review if y == True: pass",
        "Turn 4: Review list = [1,2,3,4,5]",
        "TUrn 5: Review import os, sys, json, time"
    ]

    conversation_history: List[Dict[str,str]] = [{"role":"system", "content": system_instruction}]

    for i, user_input in enumerate(prompts, start = 1):
        print(f"\n Turn {i}")
        conversation_history.append({"role":"user", "content": user_input})

        response_data, turns  = adapter.complete(conversation_history)

        conversation_history.append({"role":"assistant", "content":json.dumps(response_data)})

        print(f"\n{json.dumps(response_data)}")
        print(f"\nTurn: {i}, Input: {turns['input_token_count']}")
        print(f"\nOutput: {turns['output_token_count']}")
        print(f"\nTotal: {turns['total_token_count']}")

        if i == 3 or i == 5:
            print(f"\n Stats after turn {i}")
            stats_output(adapter, conversation_history)

    stats = adapter.stats_info(conversation_history)
    stats_output(adapter, conversation_history)


if __name__ == "__main__":
    main()