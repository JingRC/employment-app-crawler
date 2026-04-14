from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import run_priority_market_expansion as priority


DATA_DIR = Path(__file__).resolve().parent / "data"
FOLLOWUP_SUMMARY_PATH = DATA_DIR / "followup_market_expansion_last_result.json"
FOLLOWUP_CHECKPOINT_PATH = DATA_DIR / "followup_market_expansion_checkpoint.json"


FOLLOWUP_PHASES = [
    "ncss24365-campus-official",
    "healthr-national-vertical",
    "healthr-doctor-national",
    "buildhr-national-cost",
    "chenhr-national-chemcore",
    "qlrc-shandong-market",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wait for the current crawler task to finish, then run a follow-up market expansion wave.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend API base URL.")
    parser.add_argument("--start-batch", type=int, default=1, help="1-based batch index for the follow-up run.")
    parser.add_argument("--resume", action="store_true", help="Resume from the local checkpoint when phases and base_url match.")
    parser.add_argument("--max-retries", type=int, default=1, help="Retry count for a failed follow-up batch before moving on.")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="Polling interval while waiting for the current task to finish.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue follow-up batches after failures.")
    parser.add_argument("--max-batches", type=int, default=0, help="Optional cap for the follow-up run.")
    parser.add_argument("--dry-run", action="store_true", help="Print the follow-up phases without executing.")
    return parser.parse_args(argv)


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def write_followup_status(args: argparse.Namespace, current_state: str, *, waiting_for_idle: bool, finished: bool) -> None:
    summary = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "selected_phases": list(FOLLOWUP_PHASES),
        "start_batch": int(args.start_batch or 1),
        "waiting_for_idle": waiting_for_idle,
        "finished": finished,
        "current_state": current_state,
    }
    checkpoint = {
        "base_url": args.base_url,
        "selected_phases": list(FOLLOWUP_PHASES),
        "start_batch": int(args.start_batch or 1),
        "next_batch": int(args.start_batch or 1),
        "waiting_for_idle": waiting_for_idle,
        "finished": finished,
        "current_state": current_state,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    priority.write_summary(summary, FOLLOWUP_SUMMARY_PATH)
    priority.write_checkpoint(checkpoint, FOLLOWUP_CHECKPOINT_PATH)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    phases_arg = ",".join(FOLLOWUP_PHASES)
    if args.dry_run:
        return priority.main([
            "--base-url", args.base_url,
            "--phases", phases_arg,
            "--start-batch", str(args.start_batch),
            *( ["--resume"] if args.resume else [] ),
            "--max-retries", str(args.max_retries),
            "--summary-path", str(FOLLOWUP_SUMMARY_PATH),
            "--checkpoint-path", str(FOLLOWUP_CHECKPOINT_PATH),
            "--dry-run",
            *( ["--max-batches", str(args.max_batches)] if args.max_batches > 0 else [] ),
        ])

    status = priority.get_status(args.base_url)
    current_state = str(status.get("status") or "").strip().lower()
    write_followup_status(args, current_state, waiting_for_idle=current_state in {"running", "cancelling"}, finished=False)
    if current_state in {"running", "cancelling"}:
        log(f"检测到当前任务仍在执行，先等待其结束后再启动第二波补量。当前状态: {current_state}")
    else:
        log("当前没有执行中的 crawler 任务，直接启动第二波补量。")

    priority.wait_until_idle(args.base_url, poll_seconds=args.poll_seconds)
    write_followup_status(args, "idle", waiting_for_idle=False, finished=False)
    log("当前任务已结束，开始执行第二波补量。")

    next_args = [
        "--base-url", args.base_url,
        "--phases", phases_arg,
        "--start-batch", str(args.start_batch),
        "--max-retries", str(args.max_retries),
        "--summary-path", str(FOLLOWUP_SUMMARY_PATH),
        "--checkpoint-path", str(FOLLOWUP_CHECKPOINT_PATH),
    ]
    if args.resume:
        next_args.append("--resume")
    if args.continue_on_error:
        next_args.append("--continue-on-error")
    if args.max_batches > 0:
        next_args.extend(["--max-batches", str(args.max_batches)])
    return priority.main(next_args)


if __name__ == "__main__":
    raise SystemExit(main())