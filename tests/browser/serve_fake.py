"""Sobe o ScribeFlow de verdade numa pasta temporária, com um Hugging Face falso, para os testes de navegador. Imprime a URL e fica rodando."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.helpers import Env, LiveServer, install_fake_llama  # noqa: E402

env = Env(fake_hf=True)
if "--with-model" in sys.argv:   # já com um modelo «baixado» e um motor de IA falso
    install_fake_llama()
    (env.home / "models").mkdir(parents=True, exist_ok=True)
    (env.home / "models" / "Qwen3.5-2B-Heretic-Q4_K_M.gguf").write_bytes(b"GGUF" + b"0" * 1000)
srv = LiveServer(env)
print(srv.base, flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    srv.close()
    env.close()
