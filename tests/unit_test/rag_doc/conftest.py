import sys
from pathlib import Path

# rag-doc is an independent image under infra/; expose it to the unit tests
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra" / "rag-doc"))
