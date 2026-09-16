import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cert_store


@pytest.fixture
def clean_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_users.db"
    monkeypatch.setattr(cert_store, "DB_PATH", str(db_file))
    cert_store.init_db()
    return db_file


def test_default_admin_accounts_seeded(clean_db):
    users = cert_store.list_users()
    usernames = [u["username"] for u in users]
    assert "admin" in usernames
    assert "sk" in usernames

    admin_auth = cert_store.authenticate_user("admin", "cBi19rabI7Ogl8HFjJKjEZDH")
    assert admin_auth is not None
    assert admin_auth["role"] == "admin"
    assert admin_auth["username"] == "admin"

    sk_auth = cert_store.authenticate_user("sk", "cBi19rabI7Ogl8HFjJKjEZDH")
    assert sk_auth is not None
    assert sk_auth["role"] == "admin"


def test_create_and_authenticate_creator(clean_db):
    ok, msg = cert_store.create_user("staff_member", "SecurePass123", "Staff Member", role="creator")
    assert ok is True

    assert cert_store.authenticate_user("staff_member", "WrongPassword") is None

    auth = cert_store.authenticate_user("staff_member", "SecurePass123")
    assert auth is not None
    assert auth["username"] == "staff_member"
    assert auth["role"] == "creator"
    assert auth["full_name"] == "Staff Member"


def test_user_password_update_and_deactivation(clean_db):
    cert_store.create_user("temp_user", "OldPassword123", "Temp")
    
    ok, _ = cert_store.update_user_password("temp_user", "NewPassword456")
    assert ok is True
    assert cert_store.authenticate_user("temp_user", "OldPassword123") is None
    assert cert_store.authenticate_user("temp_user", "NewPassword456") is not None

    ok, _ = cert_store.toggle_user_status("temp_user", is_active=False)
    assert ok is True
    assert cert_store.authenticate_user("temp_user", "NewPassword456") is None

    cert_store.toggle_user_status("temp_user", is_active=True)
    assert cert_store.authenticate_user("temp_user", "NewPassword456") is not None


def test_delete_user_safeguards(clean_db):
    cert_store.create_user("to_delete", "Password123")
    
    ok, err = cert_store.delete_user("to_delete", current_user="to_delete")
    assert ok is False

    ok, _ = cert_store.delete_user("to_delete", current_user="admin")
    assert ok is True
    assert cert_store.authenticate_user("to_delete", "Password123") is None
