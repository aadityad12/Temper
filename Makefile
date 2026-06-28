.PHONY: run-cloud run-cloud-offline run-mock validate-schemas install-cloud install-local demo test-local test-cloud test-integration

install-cloud:
	cd cloud && python -m venv .venv && .venv/bin/pip install -r requirements.txt

install-local:
	cd local && python -m venv .venv && .venv/bin/pip install -r requirements.txt

run-cloud:
	cd cloud && .venv/bin/python main.py

run-cloud-offline:
	cd cloud && CLOUD_OFFLINE=true .venv/bin/python main.py

test-integration:
	cd local && CLOUD_OFFLINE=true .venv/bin/python test_integration.py

test-cloud:
	git checkout fixtures/villain_env/ && rm -f fixtures/villain_env/skills/get_order_usage.md fixtures/villain_env/tools/get_order.json
	cd local && TEMPER_OFFLINE=false ANTIGRAVITY_BASE_URL=http://localhost:8001 .venv/bin/python eval.py && TEMPER_OFFLINE=false ANTIGRAVITY_BASE_URL=http://localhost:8001 .venv/bin/python patch.py
	git checkout fixtures/villain_env/ && rm -f fixtures/villain_env/skills/get_order_usage.md fixtures/villain_env/tools/get_order.json

run-mock:
	cd local && .venv/bin/python mock_server.py

demo:
	cd local && .venv/bin/python demo.py

test-local:
	git checkout fixtures/villain_env/ && rm -f fixtures/villain_env/skills/get_order_usage.md fixtures/villain_env/tools/get_order.json
	cd local && TEMPER_OFFLINE=true .venv/bin/python eval.py && TEMPER_OFFLINE=true .venv/bin/python patch.py
	git checkout fixtures/villain_env/ && rm -f fixtures/villain_env/skills/get_order_usage.md fixtures/villain_env/tools/get_order.json

validate-schemas:
	cd local && .venv/bin/python -c "\
import json, jsonschema, pathlib; \
meta = json.loads(pathlib.Path('../schemas/eval_report.schema.json').read_text()); \
bundle = json.loads(pathlib.Path('../schemas/environment_bundle.schema.json').read_text()); \
r = json.loads(pathlib.Path('../fixtures/sample_eval_report.json').read_text()); \
b = json.loads(pathlib.Path('../fixtures/sample_bundle.json').read_text()); \
jsonschema.validate(r, meta); print('eval_report fixture OK'); \
jsonschema.validate(b, bundle); print('environment_bundle fixture OK')"
