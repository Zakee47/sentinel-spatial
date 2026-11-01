from drone.run import build_parser


def test_live_recording_and_twin_options() -> None:
    args = build_parser().parse_args(
        [
            "--mode",
            "live",
            "--source",
            "screen:1,2,640,480",
            "--record",
            "runs/live1",
            "--record-every",
            "0.5",
            "--build-twin-on-land",
            "survey.json",
            "--max-seconds",
            "40",
        ]
    )
    assert args.record == "runs/live1"
    assert args.record_every == 0.5
    assert args.build_twin_on_land == "survey.json"
    assert args.max_s == 40


def test_build_twin_option_without_survey() -> None:
    args = build_parser().parse_args(["--build-twin-on-land"])
    assert args.build_twin_on_land == ""
