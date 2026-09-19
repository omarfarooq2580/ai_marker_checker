# Python Project

A high-performance Python application built with modern environment and dependency management powered by [`uv`](https://github.com/astral-sh/uv).

---

## 📋 Prerequisites

Ensure you have Python 3.8+ installed. While `uv` can automatically download and manage Python versions for you, having a working base installation is recommended.

### Installing `uv`

If you don't have `uv` installed, install it using one of the following official installation methods:

#### macOS / Linux
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.sh | iex"
```

#### Via Homebrew (macOS) / pip
```bash
brew install uv
# OR
pip install uv
```

Verify your installation:
```bash
uv --version
```

---

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/omarfarooq2580/ai_marker_checker
cd ai_marker_checker
```

### 2. Sync Dependencies
To automatically create the virtual environment (`.venv`), download the required Python version (if missing), and install all locked dependencies from `uv.lock`:
```bash
uv sync
```

### 3. Run the Application
in the terminal, app your openrouter key using `$env:OPENROUTER_API_KEY="sk-or-v1-your-actual-key-here"`
You don't need to manually activate the virtual environment! Use `uvicorn app:app1 --reload --port 8000` to execute scripts directly within the environment context:

```bash
uvicorn app:app1 --reload --port 8000
```

---

### Option B: For Collaborators NOT Using `uv`
If team members or contributors prefer standard Python tooling (`venv` + `pip`), they can still use this repository:

1. Create and activate a standard virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
2. Install the package in editable mode:
   ```bash
   pip install -e .
   ```
   *(If a `requirements.txt` is exported, they can also run `pip install -r requirements.txt`)*
