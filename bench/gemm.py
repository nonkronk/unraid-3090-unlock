#!/usr/bin/env python3
"""CUDA Tensor Core GEMM throughput; no persistent package installation."""
import statistics
import torch

N = 8192
REPEATS = 15
ROUNDS = 3
WARMUP = 5

torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False
torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False
if hasattr(torch.backends.cuda.matmul, "allow_fp16_accumulation"):
    torch.backends.cuda.matmul.allow_fp16_accumulation = False

if torch.version.cuda is None:
    raise SystemExit(
        f"PyTorch {torch.__version__} is a CPU-only build. Install the CUDA build:\n"
        "  python -m pip uninstall -y torch\n"
        "  python -m pip install -r bench/requirements.txt"
    )
if not torch.cuda.is_available():
    raise SystemExit(
        f"PyTorch was built for CUDA {torch.version.cuda} but no usable GPU was found. "
        "Check that nvidia-smi lists the GPU and that its 'CUDA Version' is at least "
        f"{torch.version.cuda}."
    )

print("GPU:", torch.cuda.get_device_name(0))
print("PyTorch:", torch.__version__)
for label, dtype in (("FP16", torch.float16), ("BF16", torch.bfloat16)):
    a = torch.randn((N, N), device="cuda", dtype=dtype)
    b = torch.randn((N, N), device="cuda", dtype=dtype)
    for _ in range(WARMUP):
        torch.matmul(a, b)
    torch.cuda.synchronize()

    results = []
    for _ in range(ROUNDS):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        for _ in range(REPEATS):
            torch.matmul(a, b)
        end.record()
        torch.cuda.synchronize()
        seconds = start.elapsed_time(end) / 1000.0
        results.append((2 * N**3 * REPEATS) / seconds / 1e12)

    print(f"{label}: {statistics.median(results):.2f} TFLOPS (median of {ROUNDS} rounds)")
