"""Implemented standalone controls, separate from the frozen phone/CUSTOMVIEW contract."""

GLASSDOC_OPERATION_CONTRACT = {
    "operator": "glasses",
    "physical_acceptance": "pending",
    "startup": {
        "requires_selection": True,
        "modes": ["normal", "listening"],
        "select": "swipe",
        "start": "single_tap",
        "resume": "explicit_selection",
    },
    "capture": {
        "camera_path": "camera2",
        "manual_shot": "single_tap_while_waiting",
        "retake": "single_tap_during_review",
        "finish": "double_tap_after_last_visible_review",
        "review_visible_seconds": 3,
        "commit": "local_before_http",
        "camera_requests_during_review": False,
        "privacy_led": "device_controlled_no_override",
    },
    "listening": {"finish": "double_tap_in_listening_phase"},
    "answers": {
        "delivery": "answer-bundle",
        "next_previous": "swipe",
        "menu_select": "single_tap",
        "menu_back": "double_tap",
        "exit": "two_double_taps_within_3_seconds",
        "offline_after_download": True,
    },
    "display_sleep": "system_timeout_not_instant",
}
