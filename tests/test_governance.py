from trading_core.governance import assert_product_merge_allowed, is_protected_core_path


def test_core_governance_paths_are_machine_protected():
    assert is_protected_core_path("app/trading_core/policy.py")
    assert is_protected_core_path("app/trading_core/providers/secrets.py")
    assert is_protected_core_path("app/trading_core/resources/sql/003_autonomy.sql")


def test_triad_product_paths_remain_autonomous():
    assert is_protected_core_path("app/products/triad/static/development.js")
    assert not is_protected_core_path("app/products/triad/static/product.html")
    assert not is_protected_core_path("app/products/triad/product_app.py")
    assert not is_protected_core_path("docs/UI.md")
    assert_product_merge_allowed(
        [
            "app/products/triad/static/product.html",
            "app/products/triad/product_app.py",
            "docs/UI.md",
        ]
    )


def test_product_merge_rejects_core_governance_changes():
    try:
        assert_product_merge_allowed(["app/trading_core/providers/control.py"])
    except PermissionError as exc:
        assert "protected Core or private scope" in str(exc)
    else:
        raise AssertionError("protected Core governance change was not rejected")
