BUILD ?= build
JOBS ?= 4
RUN_ID ?= diagnostic
PROFILE ?= diagnostic
CHECKOUT ?= .
SOURCE_COMMIT ?=
EVIDENCE ?=
CORPUS ?= data/demo
DATASET ?= data/demo-prepared
TRAIN_DIR ?= runs/demo-training
NETWORK ?= models/diagnostic-v2.cai
PAIRS ?= 200
NODES ?= 500
SEED ?= 17
STEPS ?= 1000
BATCH ?= 512
WIDTH ?= 64
WORKERS ?= 4
MATCH_CONFIG ?= config/arena-demo.json
ARENA_DIR ?= runs/arena-demo
PYTHON ?= .venv/bin/python
.PHONY: bootstrap doctor build test lab-test data selfplay train export-net arena strength-report perft demo bench stress docs acceptance verify release
bootstrap:
	uv sync --frozen --extra oracle
	npm ci --ignore-scripts
doctor:
	uv run --frozen --extra oracle python tools/doctor.py
build:
	cmake -S . -B $(BUILD) -G Ninja -DCMAKE_BUILD_TYPE=Release -DCAISSA_NETWORK_WIDTH=$(WIDTH)
	cmake --build $(BUILD) -j $(JOBS)
test: build
	ctest --test-dir $(BUILD) --output-on-failure
lab-test: test
	$(PYTHON) tools/check_perft.py --engine $(BUILD)/caissa
	$(PYTHON) -m tests.statistics_test
	$(PYTHON) tests/format_controls.py --engine $(BUILD)/caissa --network $(NETWORK)
data: selfplay
selfplay: build
	$(PYTHON) -m training.corpus --engine $(BUILD)/caissa --pairs $(PAIRS) --nodes $(NODES) --workers $(WORKERS) --output $(CORPUS)
train:
	@if [ ! -f "$(DATASET)/DATASET.json" ]; then $(PYTHON) -m training.prepare "$(CORPUS)" "$(DATASET)"; fi
	@if [ -f "$(TRAIN_DIR)/CHECKPOINTS.json" ]; then $(PYTHON) -m training.train "$(DATASET)" "$(TRAIN_DIR)" --seed $(SEED) --steps $(STEPS) --batch $(BATCH) --width $(WIDTH) --resume; else $(PYTHON) -m training.train "$(DATASET)" "$(TRAIN_DIR)" --seed $(SEED) --steps $(STEPS) --batch $(BATCH) --width $(WIDTH); fi
export-net:
	$(PYTHON) -m training.export $(TRAIN_DIR)/best.pt $(TRAIN_DIR)/best.cai
arena: build
	$(PYTHON) -m arena.run $(MATCH_CONFIG) $(ARENA_DIR) --workers 2
strength-report:
	$(PYTHON) -m arena.statistics $(ARENA_DIR)
perft: build
	$(PYTHON) tools/check_perft.py --engine $(BUILD)/caissa
demo: build
	npm run build
	npm start
bench: build
	$(BUILD)/caissa --eval-bench $(NETWORK) 1000000
stress: build
	$(BUILD)/network_test $(NETWORK) 1000000
	$(PYTHON) tools/differential.py --engine $(BUILD)/caissa --positions 100000 --output runs/$(RUN_ID)-rules
	$(PYTHON) tools/protocol_audit.py --engine $(BUILD)/caissa --sequences 10000 --output runs/$(RUN_ID)-protocol
docs:
	$(PYTHON) tools/check_docs.py
	$(PYTHON) tools/diagrams.py
acceptance:
	$(PYTHON) -m tools.acceptance --run-id $(RUN_ID) --profile $(PROFILE)
verify:
	@test -n "$(EVIDENCE)" -a -n "$(SOURCE_COMMIT)" || (echo 'EVIDENCE and trusted SOURCE_COMMIT are required'; exit 2)
	$(PYTHON) -m verification.verify $(EVIDENCE) --checkout $(CHECKOUT) --expected-commit $(SOURCE_COMMIT) --profile $(PROFILE)
release:
	@test "$(PROFILE)" = full || (echo 'Release requires PROFILE=full and independently verified full evidence'; exit 2)
	$(MAKE) verify PROFILE=full EVIDENCE=$(EVIDENCE) SOURCE_COMMIT=$(SOURCE_COMMIT) CHECKOUT=$(CHECKOUT)
	$(PYTHON) -m tools.package_release --evidence $(EVIDENCE) --commit $(SOURCE_COMMIT)

.PHONY: profile
profile: build
	$(PYTHON) -m tools.performance --engine $(BUILD)/caissa --network $(NETWORK) --output runs/$(RUN_ID)-profile --load-note 'Host load was not independently checked by this target' --diagnostic

.PHONY: learning-audit
learning-audit: build
	$(PYTHON) -m tools.learning_demo --engine $(BUILD)/caissa --run-id $(RUN_ID)-learning
