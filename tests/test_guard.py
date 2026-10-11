from agent.guard import strip_unstated


def _user(text):
    return [{"role": "system", "content": "rules 1. 2. 6."}, {"role": "user", "content": text}]


def test_observed_fabrication_is_dropped():
    """The exact arguments qwen2.5:7b invented in the end-to-end run."""
    args = {"annual_kwh": 10433.9, "capacity_kw": 7, "system_cost": 28000,
            "itc_rate": 0.26, "rate_per_kwh": 0.12}
    kept, dropped = strip_unstated(args, _user("Solar at 1010 Colorado St? Assume a 7 kW system."))
    assert set(dropped) == {"system_cost", "itc_rate", "rate_per_kwh"}
    assert kept == {"annual_kwh": 10433.9, "capacity_kw": 7}


def test_stated_values_survive_in_any_common_form():
    msgs = _user("My rate is 12 cents, it cost $21,500, and I get a 30% credit. Tilt 25.")
    args = {"rate_per_kwh": 0.12, "system_cost": 21500, "itc_rate": 0.3, "tilt": 25}
    assert strip_unstated(args, msgs) == (args, {})


def test_k_suffix_and_decimals():
    msgs = _user("quoted 18k for the system at $0.135/kWh")
    kept, dropped = strip_unstated({"system_cost": 18000, "rate_per_kwh": 0.135}, msgs)
    assert not dropped


def test_numbers_in_the_system_prompt_do_not_count():
    kept, dropped = strip_unstated({"losses": 6}, _user("assess 1100 Congress Ave"))
    assert dropped == {"losses": 6}
