"""Minimal saved provider boundary; replay never calls the original provider."""

from pathlib import Path
import json

from xgap.semantic.interpretation import InterpretationFailure, InterpretationResponse, json_copy


SCHEMA = "xgap-interpretation-recording-v1"


class RecordingInterpretationProvider:
    def __init__(self, provider):
        self.provider = provider
        self.provider_id = provider.provider_id
        self.records = []

    def interpret(self, request):
        record = {"request": request.to_dict()}
        self.records.append(record)
        try:
            response = self.provider.interpret(request)
        except InterpretationFailure as error:
            record["failure"] = {"category": error.category, "message": str(error), "usage": error.usage}
            raise
        except Exception as error:
            record["failure"] = {"category": type(error).__name__,
                "message": "Interpretation provider raised an exception", "usage": {}}
            raise
        if not isinstance(response, InterpretationResponse):
            record["failure"] = {"category": "provider_contract", "message": "Provider returned an invalid response", "usage": {}}
            raise InterpretationFailure(**record["failure"])
        record["response"] = {"payload": json_copy(response.payload), "usage": response.usage,
                              "provenance": json_copy(dict(response.provenance))}
        return response

    def save(self, path):
        payload = {"schema_version": SCHEMA, "provider_id": self.provider_id, "records": self.records}
        # Explicit export only. Existing or interrupted files are never replaced.
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write("\n")


class ReplayInterpretationProvider:
    def __init__(self, payload):
        payload = json_copy(payload)
        if set(payload) != {"schema_version", "provider_id", "records"} or payload["schema_version"] != SCHEMA:
            raise ValueError("Unsupported Interpretation recording")
        if not isinstance(payload["provider_id"], str) or not payload["provider_id"] or not isinstance(payload["records"], list):
            raise ValueError("Invalid Interpretation recording identity or records")
        self.provider_id = payload["provider_id"]
        self.records = payload["records"]
        self.position = 0

    @classmethod
    def from_path(cls, path):
        with Path(path).open("rb") as stream:
            data = stream.read(4_194_305)
        if len(data) > 4_194_304:
            raise ValueError("Interpretation recording exceeds4MiB")
        return cls(json.loads(data))

    def interpret(self, request):
        if self.position >= len(self.records):
            raise InterpretationFailure("replay_exhausted", "No recorded provider call remains")
        record = self.records[self.position]
        if json.dumps(record.get("request"), sort_keys=True, allow_nan=False) != json.dumps(request.to_dict(), sort_keys=True, allow_nan=False):
            raise InterpretationFailure("replay_mismatch", "Question, context, version or request bound changed")
        if set(record) not in ({"request", "response"}, {"request", "failure"}):
            raise InterpretationFailure("replay_invalid", "Recording must have exactly one outcome")
        self.position += 1
        if "failure" in record:
            failure = record["failure"]
            error = InterpretationFailure(failure["category"], failure["message"])
            error.recorded_usage = failure["usage"]
            raise error
        response = record["response"]
        return InterpretationResponse(json_copy(response["payload"]), provenance={
            "kind": "replay", "recorded_provider_id": self.provider_id,
            "recorded_usage": response["usage"], "recorded_provenance": response["provenance"]})

    def assert_consumed(self):
        if self.position != len(self.records):
            raise ValueError("Unused Interpretation recording calls remain")
