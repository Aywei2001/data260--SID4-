
import argparse, json, os, re, sys, time
from dataclasses import dataclass
from typing import List, Dict, Any, Iterable, Tuple

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

@dataclass
class SimpleAgent:
    name:str
    system:str
    model:any 

    def respond (self, conversation: List[Dict[str, str]], task: str, title: str, content: str, strict: bool,) -> Dict[str, any]:
        history = json.dumps(conversation, indent = 2) if conversation else "no history"

        texts = (
                    f"task: {task}\n"
                    f"title: {title}\n"
                    f"content: {content}\n"
                    f"transcript: \n{history}\n"
                )

        prompt = ChatPromptTemplate.from_messages([("system", self.system),
                                                   ("human", "{input_text}")])

        chain = prompt | self.model | StrOutputParser()

        raw = chain.invoke({"input_text": texts})

        response = json.loads(raw)
        return response


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="Grocery Supply and Recall Notices")
    ap.add_argument("--content", default="Groceries will be recalled if products are contaminated, contain foregin objects or contain allergens. Products are then removed from store.")
    ap.add_argument("--email", default="student@example.com")
    ap.add_argument("--model", default=os.environ.get("SMOL_MODEL", "your-ollama-model-tag"))
    ap.add_argument("--base_url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--turns", type=int, default=1)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    try:
        llm = ChatOllama(
            model=args.model,
            temperature=0.0,
            base_url=args.base_url,
            num_ctx=2048,
            format="json", 
        )
    except Exception:
        print(
            "Failed to initialize ChatOllama. Is Ollama running and the model available?\n"
            "Try: `ollama serve` and `ollama pull <your-model-tag>`.",
            file=sys.stderr,
        )
        raise
    
    planner = SimpleAgent(name = "Planner",
                          system = ("Generate a draft with: "
                                    "3 topical tags based on the given topic."
                                    "A summary with 25 words maximum. No more than 25 words."
                                    "tags format is [tag1, tag2, tag3]"
                                    ),
                          model = llm)

    reviewer = SimpleAgent(name = "Reviewer",
                           system = ("Review everything from the Planner's output"
                                    "Planner should have generate 3 topical tags"
                                    "The summary should have 25 words maximum. No more than 25 words"
                                    "tags format is [tag1, tag2, tag3]"
                                    ),
                           model = llm)

    finalizer = SimpleAgent(name = "Finalizer",
                           system = ("Use Reviewer to finalize feedback"
                                    "Ensure output has exactly 3 topical tags and summary has 25 words maximum"
                                    "Output should be JSON with keys 'tags' and 'summary' "
                                    "tags format is [tag1, tag2, tag3]"
                                    ),
                           model = llm)

    transcript = []
    task = "Extract 3 topical tags and a summary of at most 25 words from provided title and content"

    # Planner Agent
    t0 = time.time()
    a = planner.respond(transcript, task, args.title, args.content, args.strict)
    t1 = time.time()
    transcript.append({"role": "Planner", "content": json.dumps(a)})
    print(f"\n--- Planner ({int((t1 - t0) * 1000)} ms) ---\n{json.dumps(a, indent=2)}")

    # Reviewer Agent
    t0 = time.time()
    b = reviewer.respond(transcript, task, args.title, args.content, args.strict)
    t1 = time.time()
    transcript.append({"role": "Reviewer", "content": json.dumps(b)})
    print(f"\n--- Reviewer ({int((t1 - t0) * 1000)} ms) ---\n{json.dumps(b, indent=2)}")

    # Finalization
    final = finalizer.respond(transcript, task, args.title, args.content, args.strict)
    print(f"\n Finalized Output \n{json.dumps(final, indent=2)}")



if __name__ == "__main__":
    main()