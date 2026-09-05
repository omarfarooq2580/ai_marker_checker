import os
import json
from crewai import Agent, Task, Crew, LLM

# Initialize LiteLLM via OpenRouter endpoint
openrouter_llm = LLM(
    model="openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
    api_key=os.environ.get("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1"
)

async def run_crew_analysis(catalog_data: list, repository_name: str = "scanned-repo") -> dict:
    """
    Executes a CrewAI two-agent workflow over scanner findings.
    Returns structured JSON matching the target classification schema.
    """
    # Agent 1: Primary Evidence Verifier
    signal_verifier = Agent(
        role="Signal Verification Agent",
        goal="Parse raw scanner output to extract and verify genuine AI/ML technical signals without assumptions.",
        backstory=(
            "You are an expert code auditor specializing in dependency and code analysis. "
            "You strictly check for explicit models, vector databases, frameworks, and API endpoints, "
            "ignoring false positives and unconfirmed assumptions."
        ),
        llm=openrouter_llm,
        verbose=False
    )

    # Agent 2: AI Architecture Synthesizer
    classifier_agent = Agent(
        role="AI System Classifier Agent",
        goal="Synthesize verified signals into system architecture classifications and output pure valid JSON.",
        backstory=(
            "You are a Lead AI Systems Architect. You analyze verified AI signals to determine "
            "if the codebase represents a 'RAG application', 'Agentic system', 'Traditional ML', or 'None'. "
            "You compute confidence scores and output strictly valid JSON matching the exact required schema."
        ),
        llm=openrouter_llm,
        verbose=False
    )

    # Task 1: Verification Task
    task_verify = Task(
        description=(
            f"Analyze the following scanner catalog findings for repository '{repository_name}':\n\n"
            f"{json.dumps(catalog_data, indent=2)}\n\n"
            "Identify all verified AI libraries, explicitly declared LLM model names, "
            "vector databases (e.g., Pinecone, ChromaDB), and agent orchestration frameworks (e.g., CrewAI, AutoGen)."
        ),
        expected_output="A structured report listing verified AI/ML signals, frameworks, vector DBs, and models.",
        agent=signal_verifier
    )

    # Task 2: Classification Task
    task_classify = Task(
        description=(
            "Using the verified signals report, generate the final system classification.\n"
            "Format your response EXACTLY as a single raw JSON object matching this schema:\n"
            "{\n"
            f'  "repository": "{repository_name}",\n'
            '  "ai_detected": true/false,\n'
            '  "system_type": "RAG application" | "Agentic system" | "Traditional ML" | "None",\n'
            '  "providers": ["string"],\n'
            '  "models": ["string"],\n'
            '  "frameworks": ["string"],\n'
            '  "vector_databases": ["string"],\n'
            '  "confidence": 0-100,\n'
            '  "evidence": ["string"],\n'
            '  "missing_information": ["string"]\n'
            "}\n"
            "Never invent information. If unknown, keep list fields empty. Do NOT include markdown blocks or extra text outside the JSON."
        ),
        expected_output="A valid raw JSON object matching the architecture classification schema.",
        agent=classifier_agent
    )

    # Run Sequential Workflow
    crew = Crew(
        agents=[signal_verifier, classifier_agent],
        tasks=[task_verify, task_classify],
        verbose= False
    )

    raw_result = await crew.kickoff_async()

    # Parse and Return JSON Deliverable
    try:
        clean_text = str(raw_result).strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        return {
            "repository": repository_name,
            "ai_detected": len(catalog_data) > 0,
            "system_type": "None",
            "providers": [],
            "models": [],
            "frameworks": [],
            "vector_databases": [],
            "confidence": 0,
            "evidence": [],
            "missing_information": [f"Error parsing CrewAI LLM output: {str(e)}"],
            "raw_output": str(raw_result)
        }