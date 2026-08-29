import re

_KEYWORDS = {"import", "from", "as"}


def _extract_identifiers(code_like_text):
    """Pull code identifiers (dotted names / call targets) out of a
    config string such as 'from openai import OpenAI, AsyncOpenAI'."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_\.]*", code_like_text)
    return sorted({t for t in tokens if t not in _KEYWORDS})


def _split_list(raw):
    if not raw or raw.strip().lower() == "none":
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _compile_pattern(raw):
    """Convert a spec string with '...' or '*' wildcards into a regex."""
    sentinel = "\x00WILD\x00"
    tmp = raw.replace("...", sentinel).replace("*", sentinel)
    parts = [re.escape(p) for p in tmp.split(sentinel)]
    body = ".*?".join(parts)
    if re.fullmatch(r"[A-Za-z0-9_\.]+", raw):
        return r"\b" + body + r"\b"
    return body


def _build_entry(name, packages, imports, env_vars, endpoints,
                  code_patterns, docker_images, models, ext_metrics):
    pkgs = _split_list(packages)
    imps = _split_list(imports)
    envs = _split_list(env_vars)
    eps = _split_list(endpoints)
    cps = _split_list(code_patterns)
    imgs = _split_list(docker_images)
    mdls = _split_list(models)
    exts = _split_list(ext_metrics)

    import_identifiers = set(pkgs)
    for stmt in imps:
        import_identifiers.update(_extract_identifiers(stmt))

    return {
        "technology": name,
        "raw": {
            "packages": pkgs,
            "imports": imps,
            "environment_variables": envs,
            "endpoints": eps,
            "code_patterns": cps,
            "docker_images": imgs,
            "models": mdls,
            "extensions_and_metrics": exts,
        },
        "import_identifiers": import_identifiers,
        "patterns": {
            "packages": [(p, _compile_pattern(p)) for p in pkgs],
            "environment_variables": [(p, _compile_pattern(p)) for p in envs],
            "endpoints": [(p, _compile_pattern(p)) for p in eps],
            "code_patterns": [(p, _compile_pattern(p)) for p in cps],
            "docker_images": [(p, _compile_pattern(p)) for p in imgs],
            "models": [(p, _compile_pattern(p)) for p in mdls],
            "extensions_and_metrics": [(p, _compile_pattern(p)) for p in exts],
        },
    }


TECH_MATRIX = [
    _build_entry(
        "OpenAI",
        "openai, openai-python",
        "import openai, from openai import OpenAI, AsyncOpenAI",
        "OPENAI_API_KEY, OPENAI_ORG_ID, OPENAI_PROJECT_ID, OPENAI_BASE_URL",
        "api.openai.com/v1/chat/completions, api.openai.com/v1/embeddings, api.openai.com/v1/models",
        "OpenAI(api_key=...), organization=..., project=..., client.chat.completions.create",
        "None",
        "gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo, o1-preview, o1-mini, text-embedding-3-small, text-embedding-3-large",
        "None",
    ),
    _build_entry(
        "Azure OpenAI",
        "openai",
        "from openai import AzureOpenAI, AsyncAzureOpenAI",
        "AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT_NAME",
        "*.openai.azure.com/openai/deployments/*/chat/completions",
        "AzureOpenAI(azure_endpoint=..., api_version=...), azure_deployment=...",
        "None",
        "gpt-4o, gpt-4, text-embedding-ada-002",
        "None",
    ),
    _build_entry(
        "Anthropic",
        "anthropic",
        "import anthropic, from anthropic import Anthropic, AsyncAnthropic",
        "ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL",
        "api.anthropic.com/v1/messages, api.anthropic.com/v1/complete",
        "Anthropic(api_key=...), max_tokens=...",
        "None",
        "claude-3-5-sonnet-*, claude-3-opus-*, claude-3-haiku-*, claude-2.1",
        "None",
    ),
    _build_entry(
        "Gemini",
        "google-genai, google-generativeai, google-cloud-aiplatform",
        "from google import genai, import google.generativeai as genai, from google.cloud import aiplatform",
        "GEMINI_API_KEY, GOOGLE_API_KEY, GOOGLE_APPLICATION_CREDENTIALS",
        "generativelanguage.googleapis.com/v1beta, *-aiplatform.googleapis.com",
        "genai.Client(), genai.configure(api_key=...), genai.GenerativeModel(...), GenerationConfig(...)",
        "gcr.io/deeplearning-platform-release/*",
        "gemini-1.5-pro, gemini-1.5-flash, gemini-1.0-pro, text-embedding-004",
        "None",
    ),
    _build_entry(
        "Mistral",
        "mistralai",
        "from mistralai import Mistral, from mistralai.client import MistralClient",
        "MISTRAL_API_KEY",
        "api.mistral.ai/v1/chat/completions, api.mistral.ai/v1/embeddings",
        "Mistral(api_key=...), MistralClient(api_key=...)",
        "None",
        "mistral-large-*, mistral-small-*, open-mistral-7b, open-mixtral-8x7b, codestral-*",
        "None",
    ),
    _build_entry(
        "Cohere",
        "cohere",
        "import cohere, from cohere import Client, ClientV2",
        "COHERE_API_KEY",
        "api.cohere.com/v2/chat, api.cohere.com/v1/embed, api.cohere.com/v1/rerank",
        "cohere.Client(api_key=...), cohere.ClientV2(...)",
        "None",
        "command-r-plus, command-r, embed-english-v3.0, embed-multilingual-v3.0, rerank-v3.5",
        "None",
    ),
    _build_entry(
        "Hugging Face",
        "transformers, huggingface_hub, accelerate, datasets",
        "from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline, from huggingface_hub import HfApi, login",
        "HF_TOKEN, HUGGING_FACE_HUB_TOKEN, HF_HOME, HF_HUB_CACHE",
        "huggingface.co/api/models, api-inference.huggingface.co/models/*",
        'AutoModelForCausalLM.from_pretrained(...), pipeline("text-generation", model=...)',
        "huggingface/transformers-pytorch-gpu, ghcr.io/huggingface/text-generation-inference",
        "meta-llama/*, mistralai/*, google/gemma-*, tiiuae/falcon-*",
        "None",
    ),
    _build_entry(
        "Ollama",
        "ollama",
        "import ollama, from ollama import Client",
        "OLLAMA_HOST, OLLAMA_MODELS, OLLAMA_ORIGINS",
        "localhost:11434/api/generate, localhost:11434/api/chat, localhost:11434/api/embeddings",
        "ollama.chat(...), ollama.Client(host=...)",
        "ollama/ollama",
        "llama3, llama3.1, mistral, gemma2, phi3, nomic-embed-text",
        "None",
    ),
    _build_entry(
        "vLLM",
        "vllm",
        "from vllm import LLM, SamplingParams",
        "VLLM_HOST, VLLM_PORT, VLLM_ENGINE_ITERATION_TIMEOUT_S",
        "localhost:8000/v1/chat/completions, localhost:8000/v1/models",
        "LLM(model=..., tensor_parallel_size=...), SamplingParams(temperature=...)",
        "vllm/vllm-openai",
        "meta-llama/Meta-Llama-3-8B-Instruct",
        "None",
    ),
    _build_entry(
        "PyTorch",
        "torch, torchvision, torchaudio",
        "import torch, import torch.nn as nn, import torch.optim as optim",
        "TORCH_HOME, CUDA_VISIBLE_DEVICES, PYTORCH_CUDA_ALLOC_CONF",
        "None",
        'torch.device("cuda"), nn.Module, torch.load(...), torch.save(...)',
        "pytorch/pytorch",
        "None",
        ".pt, .pth, .bin",
    ),
    _build_entry(
        "TensorFlow",
        "tensorflow, tf-keras",
        "import tensorflow as tf, from tensorflow import keras",
        "TF_CPP_MIN_LOG_LEVEL, TF_CONFIG, CUDA_VISIBLE_DEVICES",
        "localhost:8501/v1/models/*:predict",
        "tf.keras.models.Sequential(), tf.keras.models.load_model(...)",
        "tensorflow/tensorflow, tensorflow/serving",
        "None",
        ".h5, .pb, saved_model.pb",
    ),
    _build_entry(
        "ONNX",
        "onnx, onnxruntime, onnxruntime-gpu",
        "import onnx, import onnxruntime as ort",
        "ORT_CUDA_FLAGS",
        "None",
        "ort.InferenceSession(...), ort.SessionOptions()",
        "mcr.microsoft.com/onnxruntime/server",
        "None",
        "*.onnx",
    ),
    _build_entry(
        "LangChain",
        "langchain, langchain-core, langchain-community, langchain-openai, langchain-anthropic",
        "from langchain_core.prompts import PromptTemplate, from langchain_openai import ChatOpenAI, from langchain.chains import LLMChain",
        "LANGCHAIN_TRACING_V2, LANGCHAIN_API_KEY, LANGCHAIN_PROJECT, LANGCHAIN_ENDPOINT",
        "api.smith.langchain.com",
        "ChatOpenAI(model=...), prompt | llm | parser",
        "langchain/langchain",
        "None",
        "None",
    ),
    _build_entry(
        "LlamaIndex",
        "llama-index, llama-index-core, llama-index-llms-openai",
        "from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, from llama_index.llms.openai import OpenAI",
        "LLAMA_INDEX_CACHE_DIR",
        "None",
        "VectorStoreIndex.from_documents(...), Settings.llm = ...",
        "None",
        "None",
        "None",
    ),
    _build_entry(
        "CrewAI",
        "crewai, crewai-tools",
        "from crewai import Agent, Task, Crew, Process",
        "CREWAI_TELEMETRY_OPT_OUT",
        "None",
        "Agent(role=..., goal=..., backstory=..., verbose=True), Crew(...)",
        "None",
        "None",
        "None",
    ),
    _build_entry(
        "AutoGen",
        "pyautogen, autogen-agentchat, autogen-core",
        "import autogen, from autogen import AssistantAgent, UserProxyAgent, ConversableAgent",
        "AUTOGEN_USE_DOCKER",
        "None",
        "config_list = [...], ConversableAgent(name=..., llm_config=...)",
        "autogen-docker",
        "None",
        "None",
    ),
    _build_entry(
        "Semantic Kernel",
        "semantic-kernel",
        "import semantic_kernel as sk, from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion",
        "GLOBAL_LLM_SERVICE",
        "None",
        "kernel = sk.Kernel(), kernel.add_service(...)",
        "None",
        "None",
        "None",
    ),
    _build_entry(
        "Vector Databases",
        "chromadb, pinecone-client, qdrant-client, weaviate-client, pymilvus, faiss-cpu, faiss-gpu, pgvector",
        "import chromadb, from pinecone import Pinecone, import qdrant_client, import weaviate, from pymilvus import Collection, import faiss",
        "PINECONE_API_KEY, PINECONE_ENVIRONMENT, QDRANT_HOST, QDRANT_API_KEY, WEAVIATE_URL, WEAVIATE_API_KEY, MILVUS_HOST, MILVUS_PORT",
        "*.pinecone.io, *.qdrant.tech, *.weaviate.network, localhost:6333, localhost:19530, localhost:8000",
        "chromadb.PersistentClient(), Pinecone(api_key=...), qdrant_client.QdrantClient(...), weaviate.connect_to_custom(...), faiss.IndexFlatL2(...)",
        "chromadb/chroma, qdrant/qdrant, semitechnologies/weaviate, milvusdb/milvus",
        "None",
        "1536, 768, 384, cosine, euclidean, dotproduct",
    ),
]

SKIP_DIRS = {".git", "__pycache__", ".venv"}
PARSER_EXTENSIONS = {".py", ".ipynb", ".json", ".jsonl", ".env", ".yaml", ".yml", ".txt"}
OUTPUT_JSON = "ai_detection_catalog.json"
