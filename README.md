# Caissa

An original C++23 chess engine and a laboratory for testing incremental neural evaluation under controlled search budgets.

Development is in progress. See [build status](docs/BUILD_STATUS.md) for executed checks and incomplete work. No playing strength or trained-network claim is available yet.

```sh
make test
./build/caissa --version
```

The native executable uses the C++ standard library. Python/PyTorch are reserved for training and independent verification. No external chess engine is part of Caissa's runtime.

See the [contract](docs/SPECIFICATION.md) and [dependency provenance](docs/DEPENDENCIES.md).
