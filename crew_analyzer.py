import os
import json
from typing import List, Literal
from pydantic import BaseModel, Field
from crewai import Agent, Task, Crew, LLM

# Initialize LiteLLM via OpenRouter endpoint
openrouter_llm = LLM(
    model="openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
    api_key=os.environ.get("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1"
)


# --- PYDANTIC OUTPUT SCHEMA ---
class RepoAnalysis(BaseModel):
    repository: str
    ai_detected: bool
    system_type: Literal["RAG application", "Agentic system", "Traditional ML", "Self Hosted", "None"]
    classification: Literal["SANCTIONED", "UNSANCTIONED", "UNKNOWN", "REQUIRES_REVIEW"]
    reasoning: str
    providers: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    vector_databases: List[str] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    evidence: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)


def load_approved_registry():
    """Loads the approved AI systems registry from the local JSON file."""
    registry_path = os.path.join(os.path.dirname(__file__), "approved_registry.json")
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"approved_systems": []}
    return {"approved_systems": []}


async def _analyze_single_repo(repo_name: str, repo_catalog: list, registry: dict) -> dict:
    """Executes the CrewAI workflow for a single repository using Pydantic output enforcement."""

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
            f"Analyze the following scanner catalog findings specifically for repository '{repo_name}':\n\n"
            f"{json.dumps(repo_catalog, indent=2)}\n\n"
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
            f"Using the verified signals report, generate the final system classification and registry compliance analysis for '{repo_name}'.\n\n"
            f"Approved Registry:\n{json.dumps(registry, indent=2)}\n\n"
            "REGISTRY COMPLIANCE RULES:\n"
            "- Assign EXACTLY one of these four status classifications:\n"
            "  1. SANCTIONED: All detected AI providers/frameworks match an approved provider in the registry.\n"
            "  2. UNSANCTIONED: AI markers/providers are detected, but they utilize an unauthorized vendor or provider not in the approved registry.\n"
            "  3. UNKNOWN: Ambiguous signals or insufficient vendor details to determine the provider.\n"
            "  4. REQUIRES_REVIEW: Borderline, experimental tools, or unverified configurations requiring human oversight.\n\n"
            "CRITICAL CONSTRAINT: Do NOT classify any system as illegal or non-compliant under any circumstances. Restrict status outputs strictly to the four provided classification categories."
        ),
        expected_output="A structured JSON object matching the RepoAnalysis model schema.",
        agent=classifier_agent,
        output_json=RepoAnalysis  # Enforces Pydantic schema adherence directly on the LLM
    )

    crew = Crew(
        agents=[signal_verifier, classifier_agent],
        tasks=[task_verify, task_classify],
        verbose=False
    )

    raw_result = await crew.kickoff_async()

    # Extract structured dictionary directly from task execution output
    try:
        if task_classify.output and task_classify.output.json_dict:
            return task_classify.output.json_dict
        elif task_classify.output and task_classify.output.pydantic:
            return task_classify.output.pydantic.model_dump()
        
        # Fallback parsing in case output text requires manual extraction
        raw_text = str(raw_result.raw) if hasattr(raw_result, 'raw') else str(raw_result)
        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        return {
            "repository": repo_name,
            "ai_detected": len(repo_catalog) > 0,
            "system_type": "None",
            "classification": "UNKNOWN",
            "reasoning": f"Error parsing CrewAI LLM output: {str(e)}",
            "providers": [],
            "models": [],
            "frameworks": [],
            "vector_databases": [],
            "confidence": 0,
            "evidence": [],
            "missing_information": [f"Error parsing CrewAI LLM output: {str(e)}"]
        }


async def run_crew_analysis(catalog_data: list, repository_name: str = "scanned-repo") -> list:
    """
    Groups catalog data by repository and executes individual analysis per repository.
    Returns a clean array of repository JSON objects without extra metadata wrappers.
    """
    registry = load_approved_registry()

    # Group catalog items by repository_name
    grouped_catalog = {}
    for entry in catalog_data:
        repo = entry.get("repository_name", repository_name)
        if repo not in grouped_catalog:
            grouped_catalog[repo] = []
        grouped_catalog[repo].append(entry)

    if not grouped_catalog:
        grouped_catalog[repository_name] = []

    # Run single-repo analysis for each repository
    results = []
    for repo, repo_catalog in grouped_catalog.items():
        analysis = await _analyze_single_repo(repo, repo_catalog, registry)
        results.append(analysis)

    # If only 1 repository was scanned, return its JSON object directly
    if len(results) == 1:
        return results[0]

    # Return a clean list of repository JSON objects for multi-repository scans
    return results