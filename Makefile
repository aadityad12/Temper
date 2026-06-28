.PHONY: run-cloud run-mock validate-schemas install-cloud install-local demo test-local

install-cloud:
	cd cloud && python -m venv .venv && .venv/bin/pip install -r requirements.txt

install-local:
	cd local && python -m venv .venv && .venv/bin/pip install -r requirements.txt

run-cloud:
	cd cloud && .venv/bin/uvicorn main:app --reload --port 8000

run-mock:
	cd local && .venv/bin/python mock_server.py

demo:
	cd local && .venv/bin/python demo.py

test-local:
	cd local && TEMPER_OFFLINE=true .venv/bin/python eval.py && TEMPER_OFFLINE=true .venv/bin/python patch.py

validate-schemas:
	cd local && .venv/bin/python -c "\
import json, jsonschema, pathlib; \
meta = json.loads(pathlib.Path('../schemas/eval_report.schema.json').read_text()); \
bundle = json.loads(pathlib.Path('../schemas/environment_bundle.schema.json').read_text()); \
r = json.loads(pathlib.Path('../fixtures/sample_eval_report.json').read_text()); \
b = json.loads(pathlib.Path('../fixtures/sample_bundle.json').read_text()); \
jsonschema.validate(r, meta); print('eval_report fixture OK'); \
jsonschema.validate(b, bundle); print('environment_bundle fixture OK')"
