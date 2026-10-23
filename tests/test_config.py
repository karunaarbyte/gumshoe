import pytest
from pydantic import SecretStr, ValidationError

import gumshoe.mcp_server.saves as saves_module
from gumshoe.agent import AgentConfig
from gumshoe.config import PROJECT_ROOT, Settings, get_settings
from gumshoe.mcp_server.host import MAX_TEXT
from gumshoe.mcp_server.saves import default_saves_dir
from tests.conftest import SETTINGS_ENV_VARS


def test_defaults():
    s = Settings(_env_file=None)
    assert s.decider_primary == "jev"
    assert s.decider_shadow == "nimble"
    assert s.nimble_base_url == "http://localhost:11434/v1"
    assert s.nimble_model == "nimble"
    assert s.jev_base_url == "https://api.typesafe.ai/v1"
    assert s.jev_model == "jev-latest"
    assert s.request_timeout_s == 30.0


def test_env_overrides_and_converts_types(monkeypatch):
    monkeypatch.setenv("DECIDER_PRIMARY", "nimble")
    monkeypatch.setenv("DECIDER_SHADOW", "jev")
    monkeypatch.setenv("REQUEST_TIMEOUT_S", "5")
    s = Settings(_env_file=None)
    assert s.decider_primary == "nimble"
    assert s.decider_shadow == "jev"
    assert s.request_timeout_s == 5.0


def test_blank_shadow_turns_shadowing_off(monkeypatch):
    monkeypatch.setenv("DECIDER_SHADOW", "")
    assert Settings(_env_file=None).decider_shadow is None


def test_primary_and_shadow_must_differ_when_both_are_set(monkeypatch):
    monkeypatch.setenv("DECIDER_PRIMARY", "nimble")
    monkeypatch.setenv("DECIDER_SHADOW", "nimble")
    with pytest.raises(ValidationError, match="DECIDER_SHADOW"):
        Settings(_env_file=None)


def test_a_nimble_primary_alone_turns_the_default_shadow_off(monkeypatch):
    monkeypatch.setenv("DECIDER_PRIMARY", "nimble")  # the default shadow is nimble too
    s = Settings(_env_file=None)
    assert (s.decider_primary, s.decider_shadow) == ("nimble", None)


def test_a_nimble_primary_given_in_code_also_turns_the_default_shadow_off():
    assert Settings(_env_file=None, decider_primary="nimble").decider_shadow is None


def test_invalid_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("DECIDER_PRIMARY", "gpt")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_key_never_appears_in_repr_or_str(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "s3cret-key")
    s = Settings(_env_file=None)
    assert "s3cret-key" not in repr(s)
    assert "s3cret-key" not in str(s)
    assert s.jev_api_key.get_secret_value() == "s3cret-key"


def test_reads_values_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DECIDER_PRIMARY=nimble\nDECIDER_SHADOW=\n")
    s = Settings(_env_file=env)
    assert s.decider_primary == "nimble"
    assert s.decider_shadow is None


def test_get_settings_is_cached(monkeypatch):
    # the developer's real .env must not be read (it lives at the project root, not the cwd)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


@pytest.mark.parametrize("bad", ["0", "-5", "nan"])
def test_timeout_must_be_a_positive_number(monkeypatch, bad):
    monkeypatch.setenv("REQUEST_TIMEOUT_S", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_stats_defaults():
    s = Settings(_env_file=None)
    assert s.stats_db_path == PROJECT_ROOT / "data" / "decisions.db"
    assert s.cold_after_s == 300.0


@pytest.mark.parametrize("bad", ["0", "-1", "nan", "inf"])
def test_cold_after_must_be_positive_and_finite(monkeypatch, bad):
    monkeypatch.setenv("COLD_AFTER_S", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_agent_settings_defaults():
    s = Settings(_env_file=None)
    assert s.ollama_base_url == "http://localhost:11434/v1"
    assert s.persona_model_default == "ministral-3:14b"
    assert s.persona_model_dramatic == "gemma4:12b"
    assert (s.dramatic_from, s.confidence_gate, s.confirm_gate) == (2.5, 0.6, 0.8)
    assert (s.max_redrafts, s.llm_timeout_s) == (3, 60.0)


def test_agent_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("PERSONA_MODEL_DEFAULT", "small")
    monkeypatch.setenv("CONFIRM_GATE", "0.9")
    monkeypatch.setenv("MAX_REDRAFTS", "0")
    s = Settings(_env_file=None)
    assert (s.persona_model_default, s.confirm_gate, s.max_redrafts) == ("small", 0.9, 0)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CONFIRM_GATE", "0.5"),  # yes and no bands would touch
        ("CONFIRM_GATE", "1.1"),
        ("CONFIDENCE_GATE", "0"),
        ("CONFIDENCE_GATE", "1.5"),
        ("MAX_REDRAFTS", "-1"),
        ("MAX_REDRAFTS", "11"),
        ("DRAMATIC_FROM", "5"),
        ("DRAMATIC_FROM", "-1"),
        ("DRAMATIC_FROM", "nan"),
        ("LLM_TIMEOUT_S", "0"),
        ("LLM_TIMEOUT_S", "inf"),
    ],
)
def test_agent_settings_reject_values_out_of_range(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_the_project_root_holds_the_pyproject_and_the_env_file_is_read_from_there():
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert Settings.model_config["env_file"] == PROJECT_ROOT / ".env"


def test_relative_paths_resolve_against_the_project_root_not_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STATS_DB_PATH", "elsewhere/d.db")
    monkeypatch.setenv("SAVES_DIR", "my_saves")
    s = Settings(_env_file=None)
    assert s.stats_db_path == PROJECT_ROOT / "elsewhere" / "d.db"
    assert s.saves_dir == PROJECT_ROOT / "my_saves"


def test_absolute_paths_are_kept(tmp_path):
    s = Settings(_env_file=None, stats_db_path=tmp_path / "d.db", saves_dir=tmp_path / "s")
    assert (s.stats_db_path, s.saves_dir) == (tmp_path / "d.db", tmp_path / "s")


def test_zero_is_accepted_for_expiry_and_save_settings():
    s = Settings(
        _env_file=None, game_idle_minutes=0, save_retention_days=0, session_saves=0, ip_saves=0
    )
    assert (s.game_idle_minutes, s.save_retention_days, s.session_saves, s.ip_saves) == (0,) * 4


def test_new_settings_defaults():
    s = Settings(_env_file=None)
    assert s.saves_dir == PROJECT_ROOT / "saves"
    assert (s.jev_usd_per_mtok_in, s.jev_usd_per_mtok_out) == (0.0, 0.0)
    assert (s.nimble_usd_per_mtok_in, s.nimble_usd_per_mtok_out) == (0.0, 0.0)
    assert (s.cors_origins, s.cors_origin_list) == ("", ())
    assert (s.api_host, s.api_port) == ("127.0.0.1", 8000)
    assert (s.turn_timeout_s, s.max_body_bytes) == (120.0, 16384)


def test_new_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("JEV_USD_PER_MTOK_IN", "0.5")
    monkeypatch.setenv("JEV_USD_PER_MTOK_OUT", "2")
    monkeypatch.setenv("NIMBLE_USD_PER_MTOK_OUT", "0.1")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://ui.example.com")
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("TURN_TIMEOUT_S", "45")
    monkeypatch.setenv("MAX_BODY_BYTES", "4096")
    s = Settings(_env_file=None)
    assert (s.jev_usd_per_mtok_in, s.jev_usd_per_mtok_out, s.nimble_usd_per_mtok_out) == (
        0.5,
        2.0,
        0.1,
    )
    assert s.cors_origin_list == ("http://localhost:5173", "https://ui.example.com")
    assert (s.api_host, s.api_port, s.turn_timeout_s, s.max_body_bytes) == (
        "0.0.0.0",
        9000,
        45.0,
        4096,
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JEV_USD_PER_MTOK_IN", "-1"),
        ("JEV_USD_PER_MTOK_OUT", "nan"),
        ("NIMBLE_USD_PER_MTOK_IN", "inf"),
        ("NIMBLE_USD_PER_MTOK_OUT", "-0.01"),
        ("API_PORT", "0"),
        ("API_PORT", "65536"),
        ("TURN_TIMEOUT_S", "0"),
        ("TURN_TIMEOUT_S", "inf"),
        ("MAX_BODY_BYTES", "1023"),
        ("CORS_ORIGINS", "*"),
        ("CORS_ORIGINS", "http://localhost:5173,*"),
        ("CORS_ORIGINS", "http://*.example.com"),
        ("CORS_ORIGINS", "http://localhost:5173/"),
        ("CORS_ORIGINS", "localhost:5173"),
        ("CORS_ORIGINS", "ftp://example.com"),
        ("JEV_BASE_URL", "http://api.typesafe.ai/v1"),
        ("JEV_BASE_URL", "ftp://api.typesafe.ai/v1"),
        ("JEV_BASE_URL", "api.typesafe.ai/v1"),
    ],
)
def test_out_of_range_or_unsafe_values_are_refused(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "url", ["https://api.typesafe.ai/v1", "http://localhost:8080/v1", "http://127.0.0.1:9/v1"]
)
def test_jev_may_use_plain_http_only_on_this_machine(monkeypatch, url):
    monkeypatch.setenv("JEV_BASE_URL", url)
    assert Settings(_env_file=None).jev_base_url == url


def test_the_legacy_saves_variable_still_works_and_saves_dir_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("GUMSHOE_SAVES", str(tmp_path / "old"))
    assert Settings(_env_file=None).saves_dir == tmp_path / "old"
    monkeypatch.setenv("SAVES_DIR", str(tmp_path / "new"))
    assert Settings(_env_file=None).saves_dir == tmp_path / "new"


def test_both_saves_variables_are_cleared_for_every_test():
    assert {"SAVES_DIR", "GUMSHOE_SAVES"} <= SETTINGS_ENV_VARS


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"GUMSHOE_SAVES": "rel/old"},
        {"SAVES_DIR": "/abs/new"},
        {"SAVES_DIR": "a", "GUMSHOE_SAVES": "b"},
        {"SAVES_DIR": "", "GUMSHOE_SAVES": "b"},
        {"GUMSHOE_SAVES": "~/s"},
    ],
)
def test_the_mcp_server_default_saves_folder_agrees_with_the_settings(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert saves_module.PROJECT_ROOT == PROJECT_ROOT
    assert default_saves_dir() == Settings(_env_file=None).saves_dir


def test_extra_keys_in_the_env_file_are_ignored(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SOME_OTHER_TOOL_KEY=1\nDECIDER_PRIMARY=nimble\n")
    assert Settings(_env_file=env).decider_primary == "nimble"


def test_the_agent_text_limit_fits_the_host_limit():
    """The agent truncates drafts to max_text; check_reply refuses anything over MAX_TEXT."""
    assert AgentConfig().max_text <= MAX_TEXT


# --- SHADOW_RUN: one switch for "Jev with a Nimble shadow" versus "Nimble alone" -----------------


def test_the_shadow_run_is_on_by_default():
    s = Settings(_env_file=None)
    assert s.shadow_run is True and (s.decider_primary, s.decider_shadow) == ("jev", "nimble")


def test_turning_the_shadow_run_off_means_nimble_alone(monkeypatch):
    monkeypatch.setenv("SHADOW_RUN", "false")
    s = Settings(_env_file=None)
    assert s.shadow_run is False and (s.decider_primary, s.decider_shadow) == ("nimble", None)


def test_the_shadow_run_switch_overrides_the_two_role_settings(monkeypatch):
    monkeypatch.setenv("SHADOW_RUN", "false")
    monkeypatch.setenv("DECIDER_PRIMARY", "jev")
    monkeypatch.setenv("DECIDER_SHADOW", "nimble")
    s = Settings(_env_file=None)
    assert (s.decider_primary, s.decider_shadow) == ("nimble", None)


def test_the_shadow_run_switch_reads_the_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SHADOW_RUN=off\n")
    s = Settings(_env_file=env)
    assert (s.shadow_run, s.decider_primary, s.decider_shadow) == (False, "nimble", None)


def test_nimble_alone_needs_no_jev_key():
    from gumshoe.decider.backends.factory import make_decider

    s = Settings(_env_file=None, shadow_run=False)  # no key anywhere
    assert make_decider(s).name == "nimble"


def test_a_contradicting_role_setting_is_overridden_with_a_warning(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("SHADOW_RUN", "false")
    monkeypatch.setenv("DECIDER_PRIMARY", "jev")
    with caplog.at_level(logging.WARNING):
        s = Settings(_env_file=None)
    assert (s.decider_primary, s.decider_shadow) == ("nimble", None)
    assert any(
        "SHADOW_RUN=false" in r.message and "DECIDER_PRIMARY" in r.message for r in caplog.records
    )


def test_no_warning_when_the_roles_were_not_set(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("SHADOW_RUN", "false")
    with caplog.at_level(logging.WARNING):
        Settings(_env_file=None)
    assert not caplog.records


def test_public_mode_is_off_by_default():
    s = Settings(_env_file=None)
    assert s.public_origin == "" and s.public_mode is False


def test_public_origin_must_be_an_explicit_https_origin():
    secret = SecretStr("s" * 32)
    ok = Settings(
        _env_file=None, public_origin="https://gumshoe.example.com", session_secret=secret
    )
    assert ok.public_mode is True
    bad_origins = (
        "http://gumshoe.example.com",
        "https://x.example/path",
        "https://*.example.com",
        "gumshoe",
    )
    for bad in bad_origins:
        with pytest.raises(ValidationError, match="PUBLIC_ORIGIN"):
            Settings(_env_file=None, public_origin=bad, session_secret=secret)


def test_public_mode_needs_a_long_session_secret():
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(_env_file=None, public_origin="https://gumshoe.example.com")
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(
            _env_file=None,
            public_origin="https://gumshoe.example.com",
            session_secret=SecretStr("short"),
        )


def test_a_short_secret_is_fine_outside_public_mode():
    assert Settings(_env_file=None, session_secret=SecretStr("short")).public_mode is False


def test_public_origin_rejects_userinfo():
    with pytest.raises(ValueError, match="PUBLIC_ORIGIN"):
        Settings(
            _env_file=None,
            public_origin="https://user@gumshoe.example.com",
            session_secret=SecretStr("s" * 32),
        )


def test_limit_defaults():
    s = Settings(_env_file=None)
    assert (s.session_games_open, s.session_games_per_hour, s.session_turns_per_minute) == (
        3,
        20,
        30,
    )
    assert (s.ip_new_sessions_per_hour, s.ip_requests_per_minute, s.ip_turns_per_minute) == (
        10,
        300,
        60,
    )
    assert (s.session_turns_in_flight, s.ip_turns_in_flight, s.ip_games_open) == (1, 2, 6)
    assert (s.max_parallel_turns, s.turn_queue_size, s.turn_queue_wait_s) == (2, 4, 20.0)
    assert (s.shadow_parallel, s.limiter_max_keys, s.trust_proxy) == (1, 20000, False)


def test_the_global_game_cap_is_lower_in_public_mode():
    assert Settings(_env_file=None).effective_max_games == 1000
    public = Settings(
        _env_file=None,
        public_origin="https://g.example.com",
        session_secret=SecretStr("s" * 32),
    )
    assert public.effective_max_games == 200
    assert Settings(_env_file=None, max_games=7).effective_max_games == 7


def test_limits_reject_negative_numbers():
    for name in ("session_games_open", "ip_requests_per_minute", "shadow_parallel"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{name: -1})
    with pytest.raises(ValidationError):
        Settings(_env_file=None, turn_queue_wait_s=0)


def test_expiry_and_save_defaults():
    s = Settings(_env_file=None)
    got = (s.game_idle_minutes, s.save_retention_days, s.session_saves, s.ip_saves)
    assert got == (30, 30, 10, 20)


def test_expiry_and_save_settings_reject_negative_numbers():
    for name in ("game_idle_minutes", "save_retention_days", "session_saves", "ip_saves"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{name: -1})


def test_jev_budget_defaults_and_validation():
    s = Settings(_env_file=None)
    assert (s.jev_daily_tokens, s.jev_ip_daily_tokens) == (5_000_000, 300_000)
    for name in ("jev_daily_tokens", "jev_ip_daily_tokens"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{name: -1})


def test_admin_is_off_by_default_and_a_token_must_be_long():
    assert Settings(_env_file=None).admin_enabled is False
    assert Settings(_env_file=None, admin_token=SecretStr("t" * 32)).admin_enabled is True
    with pytest.raises(ValidationError, match="ADMIN_TOKEN"):
        Settings(_env_file=None, admin_token=SecretStr("short"))


def test_admin_token_never_leaks_into_errors_repr_or_str():
    secret = "sEcReT-short-value"
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, admin_token=SecretStr(secret))
    assert secret not in str(exc.value)
    assert secret not in repr(exc.value)
    good = "g" * 40
    s = Settings(_env_file=None, admin_token=SecretStr(good))
    assert good not in repr(s)
    assert good not in str(s)


@pytest.mark.parametrize("padding", ["\n", " ", "\t", "\r\n"])
def test_admin_token_with_whitespace_is_rejected(padding):
    token = "t" * 32
    for bad in (token + padding, padding + token, padding * 40):
        with pytest.raises(ValidationError, match="ADMIN_TOKEN") as exc:
            Settings(_env_file=None, admin_token=SecretStr(bad))
        assert token not in str(exc.value)


def test_decision_retention_default_and_validation():
    assert Settings(_env_file=None).decision_retention_days == 30
    with pytest.raises(ValidationError):
        Settings(_env_file=None, decision_retention_days=-1)
