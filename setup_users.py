"""Create the first administrator and optionally initial role accounts."""

from getpass import getpass

from rbac import ASSIGNABLE_ROLES, create_first_admin, create_user, has_users


def prompt_password() -> str:
    password = getpass("Password (at least 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    return password


def prompt_account() -> tuple[str, str, str]:
    username = input("Username (3-32 letters, numbers, or underscores): ").strip()
    full_name = input("Full name: ").strip()
    password = prompt_password()
    return username, full_name, password


def create_initial_users() -> None:
    if has_users():
        print("The user database is already initialized.")
        print("Sign in as an administrator to add users from the app.")
        return

    print("Create the first administrator account.")
    username, full_name, password = prompt_account()
    create_first_admin(username, full_name, password)
    print(f"Administrator '{username}' created in users.db.")

    while input("Add a role account now? (y/n): ").strip().lower() == "y":
        print("Available roles:")
        roles = list(ASSIGNABLE_ROLES.items())
        for index, (role, label) in enumerate(roles, start=1):
            print(f"  {index}. {label} ({role})")

        try:
            role_number = int(input("Choose a role number: ").strip())
            if not 1 <= role_number <= len(roles):
                raise ValueError("Choose one of the listed role numbers.")
            role = roles[role_number - 1][0]
            username, full_name, password = prompt_account()
            create_user(username, full_name, password, role)
        except (ValueError, IndexError) as exc:
            print(f"Could not create account: {exc}")
            continue

        print(f"Created {role} account '{username}'.")


if __name__ == "__main__":
    try:
        create_initial_users()
    except ValueError as exc:
        print(f"Setup failed: {exc}")
        raise SystemExit(1) from exc
