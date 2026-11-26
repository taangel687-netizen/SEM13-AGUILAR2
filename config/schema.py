import json
from pathlib import Path

EXAMPLES = json.loads(Path(__file__).with_name("openapi_examples.json").read_text(encoding="utf-8"))


def add_examples(result, generator, request, public):
    for path, methods in result["paths"].items():
        for method, operation in methods.items():
            example = EXAMPLES.get(f"{method} {path}")
            if not example:
                continue
            if "request" in example:
                media = operation.get("requestBody", {}).get("content", {}).get("application/json")
                if media:
                    media.setdefault("examples", {})["DemostracionLocal"] = {"value": example["request"]}
            response = operation["responses"].get(example["status"], {})
            media = response.get("content", {}).get("application/json")
            if media is not None and "response" in example:
                media.setdefault("examples", {})["DemostracionLocal"] = {"value": example["response"]}
    return result

