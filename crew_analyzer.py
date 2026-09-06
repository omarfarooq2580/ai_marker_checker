import os
import json
from crewai import Agent, Task, Crew, LLM

# Initialize LiteLLM via OpenRouter endpoint
openrouter_llm = LLM(
    model="openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
    api_key=os.environ.get("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1"
)

def load_approved_registry():
    """Loads the approved AI systems registry from the local JSON file."""
    registry_path = os.path.join(os.path.dirname(__file__), "approved_registry.json")
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except(json.JSONDecodeError, OSError):
            return {"approved_systems": []}
        return {"approved_systems": []}

async def run_crew_analysis(catalog_data: list, repository_name: str = "scanned-repo") -> dict:
    """
    Executes a CrewAI two-agent workflow over scanner findings and registry rules.
    Returns structured JSON matching the target classification and compliance schema.
    """
    registry = load_approved_registry()

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

    # Agent 2: AI Architecture Synthesizer & Compliance Classifier
    classifier_agent = Agent(
        role="AI System Classifier Agent",
        goal="Synthesize verified signals into system architecture and evaluate provider compliance against approved registries.",
        backstory=(
            "You are a Lead AI Governance & Systems Architect. You analyze verified AI signals to determine "
            "system type (e.g., RAG application, Agentic system) and evaluate detected providers against approved corporate registries."
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
            "vector databases (e.g., Pinecone, ChromaDB), agent orchestration frameworks (e.g., CrewAI, AutoGen), "
            "and AI providers/vendors (e.g., Azure OpenAI, OpenAI, Anthropic)."
        ),
        expected_output="A structured report listing verified AI/ML signals, frameworks, providers, vector DBs, and models.",
        agent=signal_verifier
    )

    # Task 2: Classification & Registry Compliance Task
    task_classify = Task(
        description=(
            f"Using the verified signals report, generate the final system classification and registry compliance analysis.\n\n"
            f"Approved Registry:\n{json.dumps(registry, indent=2)}\n\n"
            "REGISTRY COMPLIANCE RULES:\n"
            "- IGNORE the repository name/field in the Approved Registry. Evaluate ONLY the detected providers and frameworks against the approved list in the registry.\n"
            "- Assign EXACTLY one of these four status classifications:\n"
            "  1. SANCTIONED: All detected AI providers/frameworks match an approved provider in the registry.\n"
            "  2. UNSANCTIONED: AI markers/providers are detected, but they utilize an unauthorized vendor or provider not in the approved registry.\n"
            "  3. UNKNOWN: Ambiguous signals or insufficient vendor details to determine the provider.\n"
            "  4. REQUIRES_REVIEW: Borderline, experimental tools, or unverified configurations requiring human oversight.\n\n"
            "CRITICAL CONSTRAINT: Do NOT classify any system as illegal or non-compliant under any circumstances. Restrict status outputs strictly to the four provided classification categories.\n\n"
            "Format your response EXACTLY as a single raw JSON object matching this schema:\n"
            "{\n"
            f'  "repository": "{repository_name}",\n'
            '  "ai_detected": true/false,\n'
            '  "system_type": "RAG application" | "Agentic system" | "Traditional ML" | "None",\n'
            '  "classification": "SANCTIONED" | "UNSANCTIONED" | "UNKNOWN" | "REQUIRES_REVIEW",\n'
            '  "reasoning": "string explaining provider compliance verification",\n'
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
        expected_output="A valid raw JSON object matching the requested schema containing system classification, registry compliance, and details.",
        agent=classifier_agent
    )

    # Run Sequential Workflow
    crew = Crew(
        agents=[signal_verifier, classifier_agent],
        tasks=[task_verify, task_classify],
        verbose=False
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
            "classification": "UNKNOWN",
            "reasoning": f"Error parsing CrewAI LLM output: {str(e)}",
            "providers": [],
            "models": [],
            "frameworks": [],
            "vector_databases": [],
            "confidence": 0,
            "evidence": [],
            "missing_information": [f"Error parsing CrewAI LLM output: {str(e)}"],
            "raw_output": str(raw_result)
        }