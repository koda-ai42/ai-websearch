from ai_websearch.config import Settings
from ai_websearch.context_budget import calculate_context_budget
from ai_websearch.llama_discovery import _base_url, parse_process_output
from ai_websearch.retrieval_policy import calculate_context_retrieval_limits

assert calculate_context_budget(96001).maximum_web_tokens == 57600
default_line = "123 /opt/llama-server --host 0.0.0.0\n"
default_parsed = parse_process_output(default_line, "local")
assert default_parsed and _base_url(default_parsed[0][1], {}) == "http://127.0.0.1:8080"
line = "123 /opt/llama-server --host 0.0.0.0 --port 8081 --api-prefix /llama\n"
parsed = parse_process_output(line, "local")
assert parsed and _base_url(parsed[0][1], {}) == "http://127.0.0.1:8081/llama"
limits = calculate_context_retrieval_limits(12000)
assert limits.max_chunks <= 24 and limits.max_sources <= 8
assert Settings(_env_file=None).reranking_mode == "cross_encoder"
print("smoke test passed")
