BUILD ?= build
JOBS ?= 4
.PHONY: build test bootstrap doctor
build:
	cmake -S . -B $(BUILD) -G Ninja -DCMAKE_BUILD_TYPE=Release
	cmake --build $(BUILD) -j $(JOBS)
test: build
	ctest --test-dir $(BUILD) --output-on-failure
bootstrap:
	uv sync --extra oracle
doctor:
	uv run --frozen python tools/doctor.py
