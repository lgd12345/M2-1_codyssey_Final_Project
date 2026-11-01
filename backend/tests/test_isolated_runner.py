import pytest

from scripts.test_isolated import redact_output, regression_database_dsn


def test_runner_redacts_connection_strings_and_password_variants():
    base = "postgresql://user:private%2Fpassword@host/service_test"
    output = f"{base}\npassword=private/password\napi-private-value"
    result = redact_output(output, {"TEST_DATABASE_URL": base, "LLM_API_KEY": "api-private-value"})
    assert "private" not in result
    assert result.count("[REDACTED]") == 3


def test_runner_retargets_only_a_disposable_test_database():
    from psycopg.conninfo import conninfo_to_dict

    base = "postgresql://user:example@host/service_test"
    result = regression_database_dsn(base, "rag_regression_abc_test")
    assert conninfo_to_dict(result)["dbname"] == "rag_regression_abc_test"
    with pytest.raises(ValueError, match="isolated"):
        regression_database_dsn("postgresql://host/production", "rag_regression_abc_test")
    with pytest.raises(ValueError, match="disposable"):
        regression_database_dsn(base, "service_test")
