def print_metrics(label: str, metrics: dict) -> None:
    print(f"{label} metrics")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
