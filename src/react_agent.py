"""
Basic ReAct Agent using LangChain & Local CLI Loopback API
----------------------------------------------------------
Connects to the local CLI Loopback Server (`http://127.0.0.1:8000/v1`)
using `ChatOpenAI` and executes a multi-step Reasoning + Acting loop.
"""

import argparse
import datetime
import math
import os
import platform
import sys
from typing import Optional

from langchain_core.prompts import PromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

# LangChain classic provides the classic text-based ReAct agent loop
try:
    from langchain_classic.agents import AgentExecutor, create_react_agent
except ImportError:
    from langchain.agents import AgentExecutor, create_react_agent


# ---------------------------------------------------------
# Define Agent Tools
# ---------------------------------------------------------
@tool
def calculate(expression: str) -> str:
    """Safely evaluates a math expression. Example: '45 * (12 + 3)' or 'math.sqrt(144)'"""
    allowed_names = {
        "math": math,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
    }
    try:
        # Clean expression
        clean_expr = expression.strip().strip("'\"")
        result = eval(clean_expr, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"


@tool
def get_system_info(topic: str) -> str:
    """Provides system environment information. Valid topics: 'os', 'python', 'time', 'cwd'."""
    topic = topic.strip().lower()
    if "time" in topic or "date" in topic:
        return f"Current local time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    elif "os" in topic or "platform" in topic:
        return f"OS: {platform.system()} {platform.release()} ({platform.machine()})"
    elif "py" in topic:
        return f"Python version: {platform.python_version()} at {sys.executable}"
    elif "cwd" in topic or "dir" in topic:
        return f"Working directory: {os.getcwd()}"
    else:
        return (
            f"System summary -> OS: {platform.system()} {platform.machine()}, "
            f"Python: {platform.python_version()}, Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )


@tool
def lookup_lab_glossary(query: str) -> str:
    """Searches the Graph Engineering Lab knowledge base for definitions of graph and AI terms."""
    knowledge = {
        "graphrag": "GraphRAG enhances Retrieval-Augmented Generation by indexing document graphs and knowledge subgraphs, enabling structured multi-hop reasoning over unstructured text.",
        "knowledge graph": "A Knowledge Graph is a structured representation of real-world entities and relationships, typically stored in graph databases like Neo4j or RDF triplestores.",
        "react": "ReAct (Reasoning and Acting) is an agent paradigm that combines chain-of-thought reasoning with real-time tool execution, observing outputs before proceeding.",
        "langchain": "LangChain is a framework for developing applications powered by large language models, providing composable abstractions for chains, agents, and memory.",
        "langgraph": "LangGraph is a library within the LangChain ecosystem for building stateful, multi-agent systems and cyclic workflows with graph structures.",
        "cypher": "Cypher is a declarative graph query language used primarily with Neo4j to query and manipulate connected graph data.",
    }
    q = query.strip().lower()
    for term, definition in knowledge.items():
        if term in q or q in term:
            return f"[{term.upper()}]: {definition}"
    return f"No direct entry found for '{query}'. Available entries: {', '.join(knowledge.keys())}"


TOOLS = [calculate, get_system_info, lookup_lab_glossary]


# ---------------------------------------------------------
# ReAct Prompt Template
# ---------------------------------------------------------
REACT_PROMPT_TEMPLATE = """Answer the following questions as best you can. You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought:{agent_scratchpad}"""


def build_react_agent(
    base_url: str = "http://127.0.0.1:8000/v1",
    model_name: str = "claude",
    temperature: float = 0.0,
    verbose: bool = True,
) -> AgentExecutor:
    """Constructs the LangChain ReAct agent executor using our loopback endpoint."""
    llm = ChatOpenAI(
        base_url=base_url,
        api_key="cli-proxy",  # Dummy key accepted by loopback server
        model=model_name,
        temperature=temperature,
        use_responses_api=False,
    )

    prompt = PromptTemplate.from_template(REACT_PROMPT_TEMPLATE)
    agent = create_react_agent(llm=llm, tools=TOOLS, prompt=prompt)

    executor = AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=verbose,
        handle_parsing_errors=True,
        max_iterations=10,
    )
    return executor


def run_agent_query(executor: AgentExecutor, question: str):
    """Executes a single question and displays the reasoning trajectory."""
    print("\n" + "=" * 70)
    print(f"🎯 USER QUESTION: {question}")
    print("=" * 70)
    result = executor.invoke({"input": question})
    print("\n" + "-" * 70)
    print(f"💡 FINAL ANSWER:\n{result.get('output', result)}")
    print("-" * 70 + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description="Run LangChain ReAct Agent with CLI Loopback")
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8000/v1",
        help="Base URL for the CLI loopback server (default: http://127.0.0.1:8000/v1)",
    )
    parser.add_argument(
        "--model",
        default="claude",
        choices=["claude", "codex", "claude-3-7-sonnet", "codex-gpt-4o"],
        help="Model backend to use (claude or codex)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Optional single query to run instead of interactive mode",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run pre-configured test queries demonstrating tool use",
    )
    args = parser.parse_args()

    print(f"🤖 Initializing ReAct Agent with endpoint={args.endpoint}, model={args.model}...")
    try:
        executor = build_react_agent(base_url=args.endpoint, model_name=args.model)
    except Exception as e:
        print(f"❌ Failed to initialize agent: {e}")
        sys.exit(1)

    if args.test:
        test_questions = [
            "What is 342 multiplied by 18, plus 550? Calculate it.",
            "What is GraphRAG according to the lab glossary, and what is the current date and time on this machine?",
        ]
        for q in test_questions:
            run_agent_query(executor, q)
        return

    if args.query:
        run_agent_query(executor, args.query)
        return

    # Interactive mode
    print("\n" + "=" * 60)
    print(f"Agent ready! Powered by local '{args.model}' CLI loopback.")
    print("Available tools: calculate, get_system_info, lookup_lab_glossary")
    print("Type your question below (or 'exit' / 'quit' to stop):")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n👉 You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            run_agent_query(executor, user_input)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break


if __name__ == "__main__":
    main()
