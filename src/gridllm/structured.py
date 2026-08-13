import json

from pydantic import BaseModel, ValidationError

INSTRUCTIONS = "Reply exclusively with a valid json object conforming to this schema:"

REPAIR_SYSTEM = (
    "Fix the response you are given.\n"
    "Return only the json object conforming to the schema, with no surrounding text and no code fences."
)

DECODER = json.JSONDecoder()


def request(prompt: str, schema: type[BaseModel] | None) -> str:
    if schema is None:
        return prompt
    return f"{prompt}\n\n{INSTRUCTIONS}\n{json.dumps(schema.model_json_schema())}"


def repair(text: str, schema: type[BaseModel]) -> str:
    return (
        f"{INSTRUCTIONS}\n{json.dumps(schema.model_json_schema())}\n\n"
        f"Response to fix:\n{text}"
    )


def extract(text: str) -> dict:
    for start, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            value, _ = DECODER.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value

    raise ValueError("no json object found in the response")


def convert(text: str, schema: type[BaseModel]):
    value = extract(text)
    try:
        return schema.model_validate(value)
    except ValidationError as error:
        raise ValueError(f"json does not conform to {schema.__name__}: {error}") from error
