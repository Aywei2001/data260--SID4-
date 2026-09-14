
import argparse, json, os, re, sys, time
from dataclasses import dataclass
from typing import List, Dict, Any, Iterable, Tuple, TypedDict, Annotated
import operator
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END


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


#Agent State Node
class AgentState(TypedDict):
    title: str
    content: str
    email:str
    strict: bool
    task: str
    llm: Any
    transcript: Annotated[List[Dict[str,Any]], operator.add]
    planner_proposal: Dict[str,Any]
    reviewer_feedback: Dict[str,Any]
    final_output: Dict[str,Any]
    turn_count: int
    max_turns: int


#Planner Node carrying Planner Agent
def Planner_Node(state: AgentState):
    planner = SimpleAgent(name = "Planner",
                        system = ("Generate a draft with: "
                                "3 topical tags based on the given topic."
                                "A summary with 25 words maximum. No more than 25 words."
                                "tags format is [tag1, tag2, tag3]"
                                ),
                        model = state["llm"])

    t0 = time.time()
    suggestions = planner.respond(state["transcript"], state["task"], state["title"], state["content"], state["strict"])
    t1 = time.time()
    
    print(f"\n--- Planner ({int((t1 - t0) * 1000)} ms) ---\n{json.dumps(suggestions, indent=2)}")

    return {"planner_proposal": suggestions, "transcript":[{"role": "Planner", "content":json.dumps(suggestions)}]}


#Reviewer Node carrying Reviewer Agent
def Reviewer_Node(state: AgentState):
    reviewer = SimpleAgent(name = "Reviewer",
                        system = ("Review everything from the Planner's output"
                                "Planner should have generate 3 topical tags"
                                "The summary should have 25 words maximum. No more than 25 words"
                                "tags format is [tag1, tag2, tag3]"
                                #"Always flag any issues regardless of what is in the input"
                                #"The JSON output keys 'has_issues' is true. Any issues and failure should be explained in the 'feedback'"
                                ),
                        model = state["llm"])

    t0 = time.time()
    feedback = reviewer.respond(state["transcript"], state["task"], state["title"], state["content"], state["strict"])
    t1 = time.time()
    
    print(f"\n--- Reviewer ({int((t1 - t0) * 1000)} ms) ---\n{json.dumps(feedback, indent=2)}")

    return {"reviewer_feedback": feedback, "transcript":[{"role": "Planner", "content":json.dumps(feedback)}]}

#set up Supervisor Node
def supervisor_node(state: AgentState):
    #modify the state 
    #counter increments
    turn_count = state["turn_count"] + 1

    print(f"Turn Count: {turn_count}")

    return {"turn_count": turn_count}

#Routing
def router_logic(state: AgentState):
    #check if any proposals exist
    proposal_exists = bool(state.get("planner_proposal"))

    #look for feedback from reviewer
    reviewer_feedback = state.get("reviewer_feedback") or {}

    #check for issues in the reviewer feedback
    issues_exist = reviewer_feedback.get("has_issues", False)

    #continue to go to planner no proposals are seen
    if not proposal_exists:
        print("No proposal. Going to Planner")
        return "planner"
    #go to reviewer if no proposals but issues are found by reviewer
    if issues_exist and state["turn_count"] < state["max_turns"]:
        print("Proposal made. Going to Reviewer")
        return "reviewer"

    print("Process Complete")
    return END

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

    task = "Extract 3 topical tags and a summary of at most 25 words from provided title and content"
    initial_state: AgentState = {
        "title": args.title,
        "content": args.content,
        "email": args.email,
        "strict": args.strict,
        "task": task,
        "llm": llm,
        "transcript": [],
        "planner_proposal": {},
        "reviewer_feedback": {},
        "final_output": {},
        "turn_count": 0,
        "max_turns": args.turns
    }

    #use all the nodes to build the graph
    build = StateGraph(AgentState)

    #call the supervisor node
    build.add_node("supervisor", supervisor_node)
    #the planner and reviewer nodes should follow up
    build.add_node("planner", Planner_Node)
    build.add_node("reviewer", Reviewer_Node)
    
    build.add_edge(START, "supervisor")
    build.add_conditional_edges("supervisor", router_logic, {"planner":"planner", END:END})

    build.add_edge("planner", "reviewer")
    build.add_edge("reviewer", "supervisor")

    graph = build.compile()

    for event in graph.stream(initial_state):
            for node_name, node_output in event.items():
                print(f"Stream update from {node_name}")


    finalizer = SimpleAgent(name = "Finalizer",
                           system = ("Use Reviewer to finalize feedback"
                                    "Ensure output has exactly 3 topical tags and summary has 25 words maximum"
                                    "Output should be JSON with keys 'tags' and 'summary' "
                                    "tags format is [tag1, tag2, tag3]"
                                    ),
                           model = llm)

    transcript = []
    task = "Extract 3 topical tags and a summary of at most 25 words from provided title and content"

    # Finalization
    final = finalizer.respond(transcript, task, args.title, args.content, args.strict)
    print(f"\n Finalized Output \n{json.dumps(final, indent=2)}")



if __name__ == "__main__":
    main()