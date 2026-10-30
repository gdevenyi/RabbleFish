# Kyutai STT 1B on monster: not possible with moshi-server

1. `cargo install --locked --features cuda moshi-server` (0.6.4): `cudarc 0.16.2` does not know CUDA 12.9.
2. Unlocked build (cudarc 0.19.10 builds): PyO3 0.23.5 rejects system Python 3.14. Fixed with `PYO3_PYTHON` = uv Python 3.12.
3. Unlocked build with Python 3.12: `candle-kernels v0.9.2` fails in nvcc on `src/moe/moe_wmma.cu` for `--gpu-architecture=sm_61`. WMMA needs compute capability 7.0+, the GTX 1080 Ti is 6.1 (no tensor cores). `sentencepiece-sys v0.11.3` build script also failed (not investigated).

Conclusion: Kyutai STT via moshi-server needs compute capability >= 7.0. Not measured on monster. Logs: cargo_install_unlocked*.log.
